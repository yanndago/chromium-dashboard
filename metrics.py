from __future__ import division
from __future__ import print_function

# -*- coding: utf-8 -*-
# Copyright 2013 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = 'ericbidelman@chromium.org (Eric Bidelman)'

import datetime
import json
import logging

from google.appengine.api import users

import common
import models
import ramcache
import settings

CACHE_AGE = 86400 # 24hrs



def _truncate_day_percentage(datapoint):
  # Need 8 decimals b/c num will by multiplied by 100 to get a percentage and
  # we want 6 decimals.
  datapoint.day_percentage = float("%.*f" % (8, datapoint.day_percentage))
  return datapoint

def _is_googler(user):
  return user and user.email().endswith('@google.com')

def _clean_data(data):
  user = users.get_current_user()
  # Don't show raw percentages if user is not a googler.
  if not _is_googler(user):
    data = map(_truncate_day_percentage, data)
  return data

def _filter_metric_data(data, formatted=False):
  """Filter out unneeded metric data befor sending."""
  data = _clean_data(data)
  if not formatted:
    data = [entity.to_dict() for entity in data]

  # Remove keys that the frontend doesn't render.
  for item in data:
    item.pop('rolling_percentage', None)
    item.pop('updated', None)
    item.pop('created', None)

  return data



class TimelineHandler(common.FlaskHandler):

  HTTP_CACHE_TYPE = 'private'
  JSONIFY = True

  def make_query(self, bucket_id):
    query = self.MODEL_CLASS.all()
    query.filter('bucket_id =', bucket_id)
    # The switch to new UMA data changed the semantics of the CSS animated
    # properties. Since showing the historical data alongside the new data
    # does not make sense, filter out everything before the 2017-10-26 switch.
    # See https://github.com/GoogleChrome/chromium-dashboard/issues/414
    if self.MODEL_CLASS == models.AnimatedProperty:
      query.filter('date >=', datetime.datetime(2017, 10, 26))
    return query

  def get_template_data(self):
    try:
      bucket_id = int(self.request.args.get('bucket_id'))
    except:
      # TODO(jrobbins): Why return [] instead of 400?
      return []

    KEY = '%s|%s' % (self.MEMCACHE_KEY, bucket_id)

    keys = models.get_chunk_memcache_keys(self.make_query(bucket_id), KEY)
    chunk_dict = ramcache.get_multi(keys)

    if chunk_dict and len(chunk_dict) == len(keys):
      datapoints = models.combine_memcache_chunks(chunk_dict)
    else:
      query = self.make_query(bucket_id)
      query.order('date')
      datapoints = query.fetch(None) # All matching results.

      # Remove outliers if percentage is not between 0-1.
      #datapoints = filter(lambda x: 0 <= x.day_percentage <= 1, datapoints)

      chunk_dict = models.set_chunk_memcache_keys(KEY, datapoints)
      ramcache.set_multi(chunk_dict, time=CACHE_AGE)

    return _filter_metric_data(datapoints)


class PopularityTimelineHandler(TimelineHandler):

  MEMCACHE_KEY = 'css_pop_timeline'
  MODEL_CLASS = models.StableInstance

  def get_template_data(self):
    return super(PopularityTimelineHandler, self).get_template_data()


class AnimatedTimelineHandler(TimelineHandler):

  MEMCACHE_KEY = 'css_animated_timeline'
  MODEL_CLASS = models.AnimatedProperty

  def get_template_data(self):
    return super(AnimatedTimelineHandler, self).get_template_data()


class FeatureObserverTimelineHandler(TimelineHandler):

  MEMCACHE_KEY = 'featureob_timeline'
  MODEL_CLASS = models.FeatureObserver

  def get_template_data(self):
    return super(FeatureObserverTimelineHandler, self).get_template_data()


class FeatureHandler(common.FlaskHandler):

  HTTP_CACHE_TYPE = 'private'
  JSONIFY = True

  def __query_metrics_for_properties(self):
    datapoints = []

    # First, grab a bunch of recent datapoints in a batch.
    # That operation is fast and makes most of the iterations
    # of the main loop become in-RAM operations.
    batch_datapoints_query = self.MODEL_CLASS.all()
    batch_datapoints_query.order('-date')
    batch_datapoints_list = batch_datapoints_query.fetch(5000)
    logging.info('batch query found %r recent datapoints',
                 len(batch_datapoints_list))
    batch_datapoints_dict = {}
    for dp in batch_datapoints_list:
      if dp.bucket_id not in batch_datapoints_dict:
        batch_datapoints_dict[dp.bucket_id] = dp
    logging.info('batch query found datapoints for %r buckets',
                 len(batch_datapoints_dict))

    # For every css property, fetch latest day_percentage.
    buckets = self.PROPERTY_CLASS.all().fetch(None)
    for b in buckets:
      if b.bucket_id in batch_datapoints_dict:
        datapoints.append(batch_datapoints_dict[b.bucket_id])
      else:
        query = self.MODEL_CLASS.all()
        query.filter('bucket_id =', b.bucket_id)
        query.order('-date')
        last_result = query.get()
        if last_result:
          datapoints.append(last_result)

    # Sort list by percentage. Highest first.
    datapoints.sort(key=lambda x: x.day_percentage, reverse=True)
    return datapoints

  def get_template_data(self):
    # TODO(jrobbins): chunking is unneeded with ramcache, so we can
    # simplify this code.
    # Memcache doesn't support saving values > 1MB. Break up features into chunks
    # and save those to memcache.
    if self.MODEL_CLASS == models.FeatureObserver:
      keys = models.get_chunk_memcache_keys(
          self.PROPERTY_CLASS.all(), self.MEMCACHE_KEY)
      logging.info('looking for keys %r' % keys)
      properties = ramcache.get_multi(keys)
      logging.info('found chunk keys %r' % (properties and properties.keys()))

      # TODO(jrobbins): We are at risk of displaying a partial result if
      # memcache loses some but not all chunks.  We can't estimate the number of
      # expected cached items efficiently.  To counter that, we refresh
      # every 30 minutes via a cron.
      if not properties or self.request.args.get('refresh'):
        properties = self.__query_metrics_for_properties()

        # Memcache doesn't support saving values > 1MB. Break up list into chunks.
        chunk_keys = models.set_chunk_memcache_keys(self.MEMCACHE_KEY, properties)
        logging.info('about to store chunks keys %r' % chunk_keys.keys())
        ramcache.set_multi(chunk_keys, time=CACHE_AGE)
      else:
        properties = models.combine_memcache_chunks(properties)
    else:
      properties = ramcache.get(self.MEMCACHE_KEY)
      if properties is None:
        properties = self.__query_metrics_for_properties()
        ramcache.set(self.MEMCACHE_KEY, properties, time=CACHE_AGE)

    return _filter_metric_data(properties)


class CSSPopularityHandler(FeatureHandler):

  MEMCACHE_KEY = 'css_popularity'
  MODEL_CLASS = models.StableInstance
  PROPERTY_CLASS = models.CssPropertyHistogram

  def get_template_data(self):
    return super(CSSPopularityHandler, self).get_template_data()


class CSSAnimatedHandler(FeatureHandler):

  MEMCACHE_KEY = 'css_animated'
  MODEL_CLASS = models.AnimatedProperty
  PROPERTY_CLASS = models.CssPropertyHistogram

  def get_template_data(self):
    return super(CSSAnimatedHandler, self).get_template_data()


class FeatureObserverPopularityHandler(FeatureHandler):

  MEMCACHE_KEY = 'featureob_popularity'
  MODEL_CLASS = models.FeatureObserver
  PROPERTY_CLASS = models.FeatureObserverHistogram

  def get_template_data(self):
    return super(FeatureObserverPopularityHandler, self).get_template_data()


# TODO(jrobbins): Is this ever called?  I don't see what calls it.
# And, I don't see recent requests for it in the server logs.
# The CL that added it only added this class, no caller.
class FeatureBucketsHandler(common.FlaskHandler):
  JSONIFY = True

  def get_template_data(self, prop_type):
    if prop_type == 'cssprops':
      properties = sorted(
          models.CssPropertyHistogram.get_all().iteritems(), key=lambda x:x[1])
    else:
      properties = sorted(
          models.FeatureObserverHistogram.get_all().iteritems(), key=lambda x:x[1])

    return properties


app = common.FlaskApplication([
  ('/data/timeline/cssanimated', AnimatedTimelineHandler),
  ('/data/timeline/csspopularity', PopularityTimelineHandler),
  ('/data/timeline/featurepopularity', FeatureObserverTimelineHandler),
  ('/data/csspopularity', CSSPopularityHandler),
  ('/data/cssanimated', CSSAnimatedHandler),
  ('/data/featurepopularity', FeatureObserverPopularityHandler),
  ('/data/blink/<string:prop_type>', FeatureBucketsHandler),
], debug=settings.DEBUG)
