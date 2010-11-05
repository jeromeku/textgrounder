#!/usr/bin/python

#######
####### wiki_disambig.py
#######
####### Copyright (c) 2010 Ben Wing.
#######

import sys, re
import os, os.path
import math
from math import log
import collections
import traceback
import cPickle
import itertools
import gc
from textutil import *
from process_article_data import *
from word_distribution import WordDist
from kl_divergence import *

# FIXME:
#
# -- If coords are 0,9999, they are inaccurate, ignore them

############################################################################
#                              Documentation                               #
############################################################################

##### Quick start

# This program does disambiguation of geographic names on the TR-CONLL corpus.
# It uses data from Wikipedia to do this.  It is "unsupervised" in the sense
# that it does not do any supervised learning using the correct matches
# provided in the corpus; instead, it uses them only for evaluation purposes.

############################################################################
#                                  Globals                                 #
############################################################################

# List of stopwords
stopwords = set()

# Debug level; if non-zero, output lots of extra information about how
# things are progressing.  If > 1, even more info.
debug = 0

############################################################################
#                       Coordinates and regions                            #
############################################################################

# The coordinates of a point are spherical coordinates, indicating a
# latitude and longitude.  Latitude ranges from -90 degrees (south) to
# +90 degrees (north), with the Equator at 0 degrees.  Longitude ranges
# from -180 degrees (west) to +179.9999999.... degrees (east). -180 and +180
# degrees correspond to the same north-south parallel, and we arbitrarily
# choose -180 degrees over +180 degrees.  0 degrees longitude has been
# arbitrarily chosen as the north-south parallel that passes through
# Greenwich, England (near London).  Note that longitude wraps around, but
# latitude does not.  Furthermore, the distance between latitude lines is
# always the same (about 69 miles per degree), but the distance between
# longitude lines varies according to the latitude, ranging from about
# 69 miles per degree at the Equator to 0 miles at the North and South Pole.
#
# We divide the earth's surface into "tiling regions", using the value
# of --region-size, which is specified in miles; we convert it to degrees
# using 'miles_per_degree', which is derived from the value for the
# Earth's radius in miles.  In addition, we form a square of tiling regions
# in order to create a "statistical region", which is used to compute a
# distribution over words.  The numbe of tiling regions on a side is
# determined by --width-of-stat-region.  Note that if this is greater than
# 1, different statistical regions will overlap.
#
# To specify a region, we use region indices, which are derived from
# coordinates by dividing by degrees_per_region.  Hence, if for example
# degrees_per_region is 2, then region indices are in the range [-45,+45]
# for latitude and [-90,+90) for longitude.  In general, an arbitrary
# coordinate will have fractional region indices; however, the region
# indices of the corners of a region (tiling or statistical) will be
# integers.  Normally, we use the southwest corner to specify a region.
#
# Near the edges, tiling regions may be truncated.  Statistical regions
# will wrap around longitudinally, and will still have the same number
# of tiling regions, but may be smaller.

# Size of each region in degrees.  Determined by the --region-size option
# (however, that option is expressed in miles).
degrees_per_region = 0.0

# Minimum, maximum latitude/longitude, directly and in indices
# (integers used to index the set of regions that tile the earth)
minimum_latitude = -90.0
# The actual maximum latitude is exactly 90 (the North Pole).  But if we
# set degrees per region to be a number that exactly divides 180, and we
# set maximum_latitude = 90, then we would end up with the North Pole
# in a region by itself, something we probably don't want.
maximum_latitude = 89.999999
minimum_longitude = -180.0
maximum_longitude = 179.999999
minimum_latind = None
maximum_latind = None
minimum_longind = None
maximum_longind = None

# Radius of the earth in miles.  Used to compute spherical distance in miles,
# and miles per degree of latitude/longitude.
earth_radius_in_miles = 3963.191

# Number of miles per degree, at the equator.  For longitude, this is the
# same everywhere, but for latitude it is proportional to the degrees away
# from the equator.
miles_per_degree = math.pi * 2 * earth_radius_in_miles / 360.

# A class holding the boundary of a geographic object.  Currently this is
# just a bounding box, but eventually may be expanded to including a
# convex hull or more complex model.

class Boundary(object):
  __slots__ = ['botleft', 'topright']

  def __init__(self, botleft, topright):
    self.botleft = botleft
    self.topright = topright

  def __str__(self):
    return '%s-%s' % (self.botleft, self.topright)

  def __contains__(self, coord):
    return (coord.lat >= self.botleft.lat and
            coord.lat <= self.topright.lat and
            coord.long >= self.botleft.long and
            coord.long <= self.topright.long)

# Compute spherical distance in miles (along a great circle) between two
# coordinates.

def spheredist(p1, p2):
  if not p1 or not p2: return 1000000.
  thisRadLat = (p1.lat / 180.) * math.pi
  thisRadLong = (p1.long / 180.) * math.pi
  otherRadLat = (p2.lat / 180.) * math.pi
  otherRadLong = (p2.long / 180.) * math.pi
        
  anglecos = (math.sin(thisRadLat)*math.sin(otherRadLat)
              + math.cos(thisRadLat)*math.cos(otherRadLat)*
                math.cos(otherRadLong-thisRadLong))
  # If the values are extremely close to each other, the resulting cosine
  # value will be extremely close to 1.  In reality, however, if the values
  # are too close (e.g. the same), the computed cosine will be slightly
  # above 1, and acos() will complain.  So special-case this.
  if abs(anglecos) > 1.0:
    if abs(anglecos) > 1.000001:
      warning("Something wrong in computation of spherical distance, out-of-range cosine value %f" % anglecos)
      return 1000000.
    else:
      return 0.
  return earth_radius_in_miles * math.acos(anglecos)

# Convert a coordinate to the indices of the southwest corner of the
# corresponding tiling region.
def coord_to_tiling_region_indices(coord):
  latind = int(math.floor(coord.lat / degrees_per_region))
  longind = int(math.floor(coord.long / degrees_per_region))
  return (latind, longind)

# Convert a coordinate to the indices of the southwest corner of the
# corresponding statistical region.
def coord_to_stat_region_indices(coord):
  # When Opts.width_of_stat_region = 1, don't subtract anything.
  # When Opts.width_of_stat_region = 2, subtract 0.5*degrees_per_region.
  # When Opts.width_of_stat_region = 3, subtract degrees_per_region.
  # When Opts.width_of_stat_region = 4, subtract 1.5*degrees_per_region.
  # In general, subtract (Opts.width_of_stat_region-1)/2.0*degrees_per_region.

  # Compute the indices of the southwest region
  subval = (Opts.width_of_stat_region-1)/2.0*degrees_per_region
  lat = coord.lat - subval
  long = coord.long - subval
  if lat < minimum_latitude: lat = minimum_latitude
  if long < minimum_longitude: long += 360.

  latind, longind = coord_to_tiling_region_indices(Coord(lat, long))
  return (latind, longind)

# Convert region indices to the corresponding coordinate.
def region_indices_to_coord(latind, longind):
  return Coord(latind * degrees_per_region, longind * degrees_per_region)

# Convert region indices of a statistical region to the coordinate of the
# center of the region.
def stat_region_indices_to_center_coord(latind, longind):
  addval = Opts.width_of_stat_region/2.0
  latind += addval
  longind += addval

  coord = region_indices_to_coord(latind, longind)
  lat, long = coord.lat, coord.long
  if lat > maximum_latitude: lat = maximum_latitude
  if long > maximum_longitude: long -= 360.
  return Coord(lat, long)

############################################################################
#                             Word distributions                           #
############################################################################

# Distribution over words corresponding to a statistical region.  The following
# fields are defined in addition to base class fields:
#
#   articles: Articles used in computing the distribution.
#   num_arts: Total number of articles included.
#   incoming_links: Total number of incoming links, or None if unknown.

class RegionWordDist(WordDist):
  __slots__ = WordDist.__slots__ + ['articles', 'num_arts', 'incoming_links']

  def __init__(self):
    super(RegionWordDist, self).__init__()
    self.articles = []
    self.num_arts = 0
    self.incoming_links = 0

  def is_empty(self):
    return self.num_arts == 0

  # Add the given articles to the total distribution seen so far
  def add_articles(self, articles):
    incoming_links = 0
    if debug > 1:
      errprint("Region dist, number of articles = %s" % num_arts)
    total_arts = 0
    num_arts = 0
    old_total_tokens = self.total_tokens
    for art in articles:
      total_arts += 1
      if not art.dist:
        if not Opts.max_time_per_stage:
          warning("Saw article %s without distribution" % art)
        continue
      assert art.dist.finished
      if art.split != 'training':
        continue
      num_arts += 1
      self.articles += [art]
      self.add_word_distribution(art.dist)
      if art.incoming_links: # Might be None, for unknown link count
        incoming_links += art.incoming_links
    self.num_arts += num_arts
    self.incoming_links += incoming_links
    if num_arts and debug > 0:
      errprint("""--> Finished processing, number articles handled = %s/%s,
    skipped articles = %s, total tokens = %s/%s, incoming links = %s/%s""" %
               (num_arts, self.num_arts, total_arts - num_arts,
                self.total_tokens - old_total_tokens,
                self.total_tokens, incoming_links, self.incoming_links))

  def add_locations(self, locs):
    arts = [loc.match for loc in locs if loc.match]
    self.add_articles(arts)

  def finish_distribution(self):
    self.finish_word_distribution()

    if debug > 1:
      errprint("""For region dist, num articles = %s, total tokens = %s,
    unseen_mass = %s, incoming links = %s, overall unseen mass = %s""" %
               (self.num_arts, self.total_tokens, self.unseen_mass,
                self.incoming_links, self.overall_unseen_mass))

############################################################################
#                             Region distributions                         #
############################################################################

# Distribution over regions, as might be attached to a word.  If we have a
# set of regions, each with a word distribution, then we can imagine
# conceptually inverting the process to generate a region distribution over
# words.  Basically, for a given word, look to see what its probability is
# in all regions; normalize, and we have a word distribution.

# Fields defined:
#
#   word: Word for which the region is computed
#   regionprobs: Hash table listing probabilities associated with regions

class RegionDist(object):
  __slots__ = ['word', 'regionprobs']

  # It's expensive to compute the value for a given word so we cache word
  # distributions.
  cached_dists = LRUCache(maxsize=10000)

  def __init__(self, word=None, regionprobs=None):
    if regionprobs:
      self.regionprobs = regionprobs
    else:
      self.regionprobs = {}
    if not word:
      return
    self.word = word
    totalprob = 0.0
    # Compute and store un-normalized probabilities for all regions
    for reg in StatRegion.yield_all_nonempty_regions():
      prob = reg.worddist.lookup_word(word)
      self.regionprobs[reg] = prob
      totalprob += prob
    # Normalize the probabilities
    for (reg, prob) in self.regionprobs.iteritems():
      self.regionprobs[reg] /= totalprob

  # Return a region distribution over a given word, using a least-recently-used
  # cache to optimize access.
  @classmethod
  def get_region_dist(cls, word):
    dist = cls.cached_dists.get(word, None)
    if not dist:
      dist = RegionDist(word)
      cls.cached_dists[word] = dist
    return dist

  # Return a region distribution over a distribution over words.  This works
  # by adding up the distributions of the individual words, weighting by
  # the count of the each word.
  @classmethod
  def get_region_dist_for_word_dist(cls, worddist):
    regprobs = floatdict()
    for (word, count) in worddist.counts.iteritems():
      dist = cls.get_region_dist(word)
      for (reg, prob) in dist.regionprobs.iteritems():
        regprobs[reg] += count*prob
    totalprob = sum(regprobs.itervalues())
    for (reg, prob) in regprobs.iteritems():
      regprobs[reg] /= totalprob
    return RegionDist(regionprobs=regprobs)


############################################################################
#                           Geographic locations                           #
############################################################################

############ statistical regions ############

# This class contains values used in computing the distribution over all
# locations in the statistical region surrounding the locality in question.
# The statistical region is currently defined as a square of NxN tiling
# regions, for N = Opts.width_of_stat_region.
# The following fields are defined: 
#
#   latind, longind: Region indices of southwest-most tiling region in
#                    statistical region.
#   worddist: Distribution corresponding to region.

class StatRegion(object):
  __slots__ = ['latind', 'longind', 'worddist']
  
  # Mapping of region->locations in region, for region-based Naive Bayes
  # disambiguation.  The key is a tuple expressing the integer indices of the
  # latitude and longitude of the southwest corner of the region. (Basically,
  # given an index, the latitude or longitude of the southwest corner is
  # index*degrees_per_region, and the region includes all locations whose
  # latitude or longitude is in the half-open interval
  # [index*degrees_per_region, (index+1)*degrees_per_region).
  #
  # We don't just create an array because we expect many regions to have no
  # articles in them, esp. as we decrease the region size.  The idea is that
  # the regions provide a first approximation to the regions used to create the
  # article distributions.
  tiling_region_to_articles = listdict()

  # Mapping from center of statistical region to corresponding region object.
  # A "statistical region" is made up of a square of tiling regions, with
  # the number of regions on a side determined by `Opts.width_of_stat_region'.  A
  # word distribution is associated with each statistical region.
  corner_to_stat_region = {}

  empty_stat_region = None # Can't compute this until class is initialized
  all_regions_computed = False
  num_empty_regions = 0
  num_non_empty_regions = 0

  def __init__(self, latind, longind):
    self.latind = latind
    self.longind = longind
    self.worddist = RegionWordDist()

  # Generate the distribution for a statistical region from the tiling regions.
  def generate_dist(self):

    reglat = self.latind
    reglong = self.longind

    if debug > 1:
      errprint("Generating distribution for statistical region centered at %s"
               % region_indices_to_coord(reglat, reglong))

    # Accumulate counts for the given region
    def process_one_region(latind, longind):
      arts = StatRegion.tiling_region_to_articles.get((latind, longind), None)
      if not arts:
        return
      if debug > 1:
        errprint("--> Processing tiling region %s" %
                 region_indices_to_coord(latind, longind))
      self.worddist.add_articles(arts)

    # Process the tiling regions making up the statistical region;
    # but be careful around the edges.
    for i in range(reglat, reglat + Opts.width_of_stat_region):
      for j in range(reglong, reglong + Opts.width_of_stat_region):
        jj = j
        if jj > maximum_longind: jj = minimum_longind
        process_one_region(i, jj)

    self.worddist.finish_distribution()

  # Find the correct StatRegion for the given coordinates.
  # If none, create the region.
  @classmethod
  def find_region_for_coord(cls, coord):
    latind, longind = coord_to_stat_region_indices(coord)
    return cls.find_region_for_region_indices(latind, longind)

  # Find the StatRegion with the given indices at the southwest point.
  # If none, create the region.
  @classmethod
  def find_region_for_region_indices(cls, latind, longind,
                                     no_create_empty=False):
    statreg = cls.corner_to_stat_region.get((latind, longind), None)
    if not statreg:
      if cls.all_regions_computed:
        if not cls.empty_stat_region:
          cls.empty_stat_region = cls(None, None)
          cls.empty_stat_region.worddist.finish_distribution()
        return cls.empty_stat_region
      statreg = cls(latind, longind)
      statreg.generate_dist()
      empty = statreg.worddist.is_empty()
      if empty:
        cls.num_empty_regions += 1
      else:
        cls.num_non_empty_regions += 1
      if not empty or not no_create_empty:
        cls.corner_to_stat_region[(latind, longind)] = statreg
    return statreg

  # Generate all clss that are non-empty.
  @classmethod
  def generate_all_nonempty_regions(cls):
    errprint("Generating all non-empty statistical regions...")
    status = StatusMessage('statistical region')

    for i in xrange(minimum_latind, maximum_latind + 1):
      for j in xrange(minimum_longind, maximum_longind + 1):
        cls.find_region_for_region_indices(i, j, no_create_empty=True)
        status.item_processed()

    cls.all_regions_computed = True
    
  # Add the given article to the region map, which covers the earth in regions
  # of a particular size to aid in computing the regions used in region-based
  # Naive Bayes.
  @classmethod
  def add_article_to_region(cls, article):
    latind, longind = coord_to_tiling_region_indices(article.coord)
    cls.tiling_region_to_articles[(latind, longind)] += [article]

  @classmethod
  def yield_all_nonempty_regions(cls):
    assert cls.all_regions_computed
    return cls.corner_to_stat_region.itervalues()

############ Locations ############

# A general location (either locality or division).  The following
# fields are defined:
#
#   name: Name of location.
#   altnames: List of alternative names of location.
#   type: Type of location (locality, agglomeration, country, state,
#                           territory, province, etc.)
#   match: Wikipedia article corresponding to this location.
#   div: Next higher-level division this location is within, or None.

class Location(object):
  __slots__ = ['name', 'altnames', 'type', 'match', 'div']
  pass

# A location corresponding to an entry in a gazetteer, with a single
# coordinate.
#
# The following fields are defined, in addition to those for Location:
#
#   coord: Coordinates of the location, as a Coord object.
#   stat_region: The statistical region surrounding this location, including
#             all necessary information to determine the region-based
#             distribution.

class Locality(Location):
  # This is an optimization that causes space to be allocated in the most
  # efficient possible way for exactly these attributes, and no others.

  __slots__ = Location.__slots__ + ['coord', 'stat_region']

  def __init__(self, name, coord):
    self.name = name
    self.coord = coord
    self.altnames = []
    self.match = None
    self.stat_region = None

  def __str__(self):
    return 'Locality %s (%s) at %s, match=%s' % \
      (self.name, self.div and '/'.join(self.div.path), self.coord, self.match)

  def distance_to_coord(self, coord):
    return spheredist(self.coord, coord)

  def matches_coord(self, coord):
    return self.distance_to_coord(coord) <= Opts.max_dist_for_close_match


# A division higher than a single locality.  According to the World
# gazetteer, there are three levels of divisions.  For the U.S., this
# corresponds to country, state, county.
#
# The following fields are defined:
#
#   level: 1, 2, or 3 for first, second, or third-level division
#   path: Tuple of same size as the level #, listing the path of divisions
#         from highest to lowest, leading to this division.  The last
#         element is the same as the "name" of the division.
#   locs: List of locations inside of the division.
#   goodlocs: List of locations inside of the division other than those
#             rejected as outliers (too far from all other locations).
#   boundary: A Boundary object specifying the boundary of the area of the
#             division.  Currently in the form of a rectangular bounding box.
#             Eventually may contain a convex hull or even more complex
#             region (e.g. set of convex regions).
#   worddist: For region-based Naive Bayes disambiguation, a distribution
#           over the division's article and all locations within the region.

class Division(object):
  __slots__ = Location.__slots__ + \
    ['level', 'path', 'locs', 'goodlocs', 'boundary', 'worddist']

  # For each division, map from division's path to Division object.
  path_to_division = {}

  def __init__(self, path):
    self.name = path[-1]
    self.altnames = []
    self.path = path
    self.level = len(path)
    self.locs = []
    self.match = None
    self.worddist = None

  def __str__(self):
    return 'Division %s (%s), match=%s, boundary=%s' % \
      (self.name, '/'.join(self.path), self.match, self.boundary)

  def distance_to_coord(self, coord):
    return "Unknown"

  def matches_coord(self, coord):
    return coord in self

  # Compute the boundary of the geographic region of this division, based
  # on the points in the region.
  def compute_boundary(self):
    # Yield up all points that are not "outliers", where outliers are defined
    # as points that are more than Opts.max_dist_for_outliers away from all
    # other points.
    def yield_non_outliers():
      # If not enough points, just return them; otherwise too much possibility
      # that all of them, or some good ones, will be considered outliers.
      if len(self.locs) <= 5:
        for p in self.locs: yield p
        return
      for p in self.locs: yield p
      #for p in self.locs:
      #  # Find minimum distance to all other points and check it.
      #  mindist = min(spheredist(p, x) for x in self.locs if x is not p)
      #  if mindist <= Opts.max_dist_for_outliers: yield p

    if debug > 1:
      errprint("Computing boundary for %s, path %s, num points %s" %
               (self.name, self.path, len(self.locs)))
               
    self.goodlocs = list(yield_non_outliers())
    # If we've somehow discarded all points, just use the original list
    if not len(self.goodlocs):
      if debug > 0:
        warning("All points considered outliers?  Division %s, path %s" %
                (self.name, self.path))
      self.goodlocs = self.locs
    topleft = Coord(min(x.coord.lat for x in self.goodlocs),
                    min(x.coord.long for x in self.goodlocs))
    botright = Coord(max(x.coord.lat for x in self.goodlocs),
                     max(x.coord.long for x in self.goodlocs))
    self.boundary = Boundary(topleft, botright)

  def generate_worddist(self):
    self.worddist = RegionWordDist()
    self.worddist.add_locations([self])
    self.worddist.add_locations(self.goodlocs)
    self.worddist.finish_distribution()

  def __contains__(self, coord):
    return coord in self.boundary

  # Note that a location was seen with the given path to the location.
  # Return the corresponding Division.
  @classmethod
  def note_point_seen_in_division(cls, loc, path):
    higherdiv = None
    if len(path) > 1:
      # Also note location in next-higher division.
      higherdiv = cls.note_point_seen_in_division(loc, path[0:-1])
    # Skip divisions where last element in path is empty; this is a
    # reference to a higher-level division with no corresponding lower-level
    # division.
    if not path[-1]: return higherdiv
    if path in cls.path_to_division:
      division = cls.path_to_division[path]
    else:
      # If we haven't seen this path, create a new Division object.
      # Record the mapping from path to division, and also from the
      # division's "name" (name of lowest-level division in path) to
      # the division.
      division = cls(path)
      division.div = higherdiv
      cls.path_to_division[path] = division
      Gazetteer.lower_toponym_to_division[path[-1].lower()] += [division]
    division.locs += [loc]
    return division

############################################################################
#                             Wikipedia articles                           #
############################################################################

#####################  Article table

# Static class maintaining tables listing all articles and mapping between
# names, ID's and articles.  Objects corresponding to redirect articles
# should not be present anywhere in this table; instead, the name of the
# redirect article should point to the article object for the article
# pointed to by the redirect.
class ArticleTable(object):
  # Map from short name (lowercased) to list of Wikipedia articles.  The short
  # name for an article is computed from the article's name.  If the article
  # name has a comma, the short name is the part before the comma, e.g. the
  # short name of "Springfield, Ohio" is "Springfield".  If the name has no
  # comma, the short name is the same as the article name.  The idea is that
  # the short name should be the same as one of the toponyms used to refer to
  # the article.
  short_lower_name_to_articles = listdict()

  # Map from tuple (NAME, DIV) for Wikipedia articles of the form
  # "Springfield, Ohio", lowercased.
  lower_name_div_to_articles = listdict()

  # Mapping from article names to Article objects, using the actual case of
  # the article.
  name_to_article = {}

  # For each toponym, list of Wikipedia articles matching the name.
  lower_toponym_to_article = listdict()

  # Mapping from lowercased article names to Article objects
  lower_name_to_articles = listdict()

  articles_by_split = {}

  # Look up an article named NAME and return the associated article.
  # Note that article names are case-sensitive but the first letter needs to
  # be capitalized.
  @classmethod
  def lookup_article(cls, name):
    assert name
    return cls.name_to_article.get(capfirst(name), None)

  # Record the article as having NAME as one of its names (there may be
  # multiple names, due to redirects).  Also add to related lists mapping
  # lowercased form, short form, etc.  If IS_REDIRECT, this is a redirect to
  # an article, so don't record it again.
  @classmethod
  def record_article(cls, name, art, is_redirect=False):
    # Must pass in properly cased name
    assert name == capfirst(name)
    cls.name_to_article[name] = art
    loname = name.lower()
    cls.lower_name_to_articles[loname] += [art]
    (short, div) = compute_short_form(loname)
    if div:
      cls.lower_name_div_to_articles[(short, div)] += [art]
    cls.short_lower_name_to_articles[short] += [art]
    if art not in cls.lower_toponym_to_article[loname]:
      cls.lower_toponym_to_article[loname] += [art]
    if short != loname and art not in cls.lower_toponym_to_article[short]:
      cls.lower_toponym_to_article[short] += [art]
    if not is_redirect:
      splithash = cls.articles_by_split
      if art.split not in splithash:
        #splithash[art.split] = set()
        splithash[art.split] = []
      splitcoll = splithash[art.split]
      if isinstance(splitcoll, set):
        splitcoll.add(art)
      else:
        splitcoll.append(art)

  @classmethod
  def finish_article_distributions(cls):
    # Figure out the value of OVERALL_UNSEEN_MASS for each article.
    for table in cls.articles_by_split.itervalues():
      for art in table:
        if art.dist:
          art.dist.finish_word_distribution()

  # Find Wikipedia article matching name NAME for location LOC.  NAME
  # will generally be one of the names of LOC (either its canonical
  # name or one of the alternate name).  CHECK_MATCH is a function that
  # is passed two aruments, the location and the Wikipedia artile name,
  # and should return True if the location matches the article.
  # PREFER_MATCH is used when two or more articles match.  It is passed
  # three argument, the location and two Wikipedia article names.  It
  # should return TRUE if the first is to be preferred to the second.
  # Return the name of the article matched, or None.

  @classmethod
  def find_one_wikipedia_match(cls, loc, name, check_match, prefer_match):

    loname = name.lower()

    # Look for any articles with same name (case-insensitive) as the location,
    # check for matches
    for art in cls.lower_name_to_articles[loname]:
      if check_match(loc, art): return art

    # Check whether there is a match for an article whose name is
    # a combination of the location's name and one of the divisions that
    # the location is in (e.g. "Augusta, Georgia" for a location named
    # "Augusta" in a second-level division "Georgia").
    if loc.div:
      for div in loc.div.path:
        for art in cls.lower_name_div_to_articles[(loname, div.lower())]:
          if check_match(loc, art): return art

    # See if there is a match with any of the articles whose short name
    # is the same as the location's name
    arts = cls.short_lower_name_to_articles[loname]
    if arts:
      goodarts = [art for art in arts if check_match(loc, art)]
      if len(goodarts) == 1:
        return goodarts[0] # One match
      elif len(goodarts) > 1:
        # Multiple matches: Sort by preference, return most preferred one
        if debug > 1:
          errprint("Warning: Saw %s toponym matches: %s" %
                   (len(goodarts), goodarts))
        sortedarts = \
          sorted(goodarts, cmp=(lambda x,y:1 if prefer_match(loc, x,y) else -1),
                 reverse=True)
        return sortedarts[0]

    # No match.
    return None

  # Find Wikipedia article matching location LOC.  CHECK_MATCH and
  # PREFER_MATCH are as above.  Return the name of the article matched, or None.

  @classmethod
  def find_wikipedia_match(cls, loc, check_match, prefer_match):
    # Try to find a match for the canonical name of the location
    match = cls.find_one_wikipedia_match(loc, loc.name, check_match,
                                         prefer_match)
    if match: return match

    # No match; try each of the alternate names in turn.
    for altname in loc.altnames:
      match = cls.find_one_wikipedia_match(loc, altname, check_match,
                                           prefer_match)
      if match: return match

    # No match.
    return None

  # Find Wikipedia article matching locality LOC; the two coordinates must
  # be at most MAXDIST away from each other.

  @classmethod
  def find_match_for_locality(cls, loc, maxdist):

    def check_match(loc, art):
      dist = spheredist(loc.coord, art.coord)
      if dist <= maxdist:
        return True
      else:
        if debug > 1:
          errprint("Found article %s but dist %s > %s" %
                   (art, dist, maxdist))
        return False

    def prefer_match(loc, art1, art2):
      return spheredist(loc.coord, art1.coord) < \
        spheredist(loc.coord, art2.coord)

    return cls.find_wikipedia_match(loc, check_match, prefer_match)

  # Find Wikipedia article matching division LOC; the article coordinate
  # must be inside of the division's boundaries.

  @classmethod
  def find_match_for_division(cls, loc):

    def check_match(loc, art):
      if art.coord and art.coord in loc:
        return True
      else:
        if debug > 1:
          if not art.coord:
            errprint("Found article %s but no coordinate, so not in location named %s, path %s" %
                     (art, loc.name, loc.path))
          else:
            errprint("Found article %s but not in location named %s, path %s" %
                     (art, loc.name, loc.path))
        return False

    def prefer_match(loc, art1, art2):
      l1 = art1.incoming_links
      l2 = art2.incoming_links
      # Prefer according to incoming link counts, if that info is available
      if l1 is not None and l2 is not None:
        return l1 > l2
      else:
        # FIXME: Do something smart here -- maybe check that location is farther
        # in the middle of the bounding box (does this even make sense???)
        return True

    return cls.find_wikipedia_match(loc, check_match, prefer_match)


######################## Articles

# Compute the short form of an article name.  If short form includes a
# division (e.g. "Tucson, Arizona"), return a tuple (SHORTFORM, DIVISION);
# else return a tuple (SHORTFORM, None).

def compute_short_form(name):
  if rematch('(.*?), (.*)$', name):
    return (m_[1], m_[2])
  elif rematch('(.*) \(.*\)$', name):
    return (m_[1], None)
  else:
    return (name, None)

# A Wikipedia article for geotagging.  Defined fields, in addition to those
# of the base classes:
#
#   dist: Object containing word distribution of this article.
#   location: Corresponding location for this article.
#   stat_region: StatRegion object corresponding to this article.

class StatArticle(Article):
  __slots__ = Article.__slots__ + ['dist', 'location', 'stat_region']

  def __init__(self, **args):
    super(StatArticle, self).__init__(**args)
    self.location = None
    self.stat_region = None
    self.dist = None

  def distance_to_coord(self, coord):
    return spheredist(self.coord, coord)

  def matches_coord(self, coord):
    if self.distance_to_coord(coord) <= Opts.max_dist_for_close_match:
      return True
    if self.location and type(self.location) is Division and \
        self.location.matches_coord(coord): return True
    return False

  # Determine the region word-distribution object for a given article:
  # Create and populate one if necessary.
  def find_regworddist(self):
    loc = self.location
    if loc and type(loc) is Division:
      if not loc.worddist:
        loc.generate_worddist()
      return loc.worddist
    if not self.stat_region:
      self.stat_region = StatRegion.find_region_for_coord(self.coord)
    return self.stat_region.worddist

############################################################################
#                             Accumulate results                           #
############################################################################

class Eval(object):
  def __init__(self, incorrect_reasons):
    # Statistics on the types of instances processed
    # Total number of instances
    self.total_instances = 0
    self.correct_instances = 0
    self.incorrect_instances = 0
    self.incorrect_reasons = incorrect_reasons
    for (attrname, engname) in self.incorrect_reasons:
      setattr(self, attrname, 0)
    self.other_stats = intdict()
  
  def record_result(self, correct, reason=None):
    self.total_instances += 1
    if correct:
      self.correct_instances += 1
    else:
      self.incorrect_instances += 1
      if reason is not None:
        setattr(self, reason, getattr(self, reason) + 1)

  def record_other_stat(self, othertype):
    self.other_stats[othertype] += 1

  def output_fraction(self, header, amount, total):
    if amount > total:
      warning("Something wrong: Fractional quantity %s greater than total %s"
              % (amount, total))
    if total == 0:
      percent = "indeterminate percent"
    else:
      percent = "%5.2f%%" % (100*float(amount)/total)
    errprint("%s = %s/%s = %s" % (header, amount, total, percent))

  def output_correct_results(self):
    self.output_fraction("Percent correct", self.correct_instances,
                         self.total_instances)

  def output_incorrect_results(self):
    self.output_fraction("Percent incorrect", self.incorrect_instances,
                         self.total_instances)
    for (reason, descr) in self.incorrect_reasons:
      self.output_fraction("  %s" % descr, getattr(self, reason),
                           self.total_instances)

  def output_other_stats(self):
    for (ty, count) in self.other_stats.iteritems():
      errprint("%s = %s" % (ty, count))

  def output_results(self):
    if not self.total_instances:
      warning("Strange, no instances found at all; perhaps --eval-format is incorrect?")
      return
    errprint("Number of instances = %s" % self.total_instances)
    self.output_correct_results()
    self.output_incorrect_results()
    self.output_other_stats()

class EvalWithCandidateList(Eval):
  def __init__(self, incorrect_reasons, max_individual_candidates=5):
    super(EvalWithCandidateList, self).__init__(incorrect_reasons)
    self.max_individual_candidates = max_individual_candidates
    # Toponyms by number of candidates available
    self.total_instances_by_num_candidates = intdict()
    self.correct_instances_by_num_candidates = intdict()
    self.incorrect_instances_by_num_candidates = intdict()

  def record_result(self, correct, reason, num_arts):
    super(EvalWithCandidateList, self).record_result(correct, reason)
    self.total_instances_by_num_candidates[num_arts] += 1
    if correct:
      self.correct_instances_by_num_candidates[num_arts] += 1
    else:
      self.incorrect_instances_by_num_candidates[num_arts] += 1

  def output_table_by_num_candidates(self, table, total):
    for i in range(0, 1+self.max_individual_candidates):
      self.output_fraction("  With %d  candidates" % i, table[i], total)
    items = sum(val for key, val in table.iteritems()
                if key > self.max_individual_candidates)
    self.output_fraction("  With %d+ candidates" %
                           (1+self.max_individual_candidates),
                         items, total)

  def output_correct_results(self):
    super(EvalWithCandidateList, self).output_correct_results()
    self.output_table_by_num_candidates(
      self.correct_instances_by_num_candidates, self.correct_instances)

  def output_incorrect_results(self):
    super(EvalWithCandidateList, self).output_incorrect_results()
    self.output_table_by_num_candidates(
      self.incorrect_instances_by_num_candidates, self.incorrect_instances)

class EvalWithRank(Eval):
  def __init__(self, max_rank_for_credit=10):
    super(EvalWithRank, self).__init__(incorrect_reasons=[])
    self.max_rank_for_credit = max_rank_for_credit
    self.incorrect_by_exact_rank = intdict()
    self.correct_by_up_to_rank = intdict()
    self.incorrect_past_max_rank = 0
    self.total_credit = 0
  
  def record_result(self, rank):
    assert rank >= 1
    correct = rank == 1
    super(EvalWithRank, self).record_result(correct, reason=None)
    if rank <= self.max_rank_for_credit:
      self.total_credit += self.max_rank_for_credit + 1 - rank
      self.incorrect_by_exact_rank[rank] += 1
      for i in xrange(rank, self.max_rank_for_credit + 1):
        self.correct_by_up_to_rank[i] += 1
    else:
      self.incorrect_past_max_rank += 1

  def output_correct_results(self):
    super(EvalWithRank, self).output_correct_results()
    possible_credit = self.max_rank_for_credit*self.total_instances
    self.output_fraction("Percent correct with partial credit",
                         self.total_credit, possible_credit)
    for i in xrange(2, self.max_rank_for_credit + 1):
      self.output_fraction("  Correct is at or above rank %s" % i,
                           self.correct_by_up_to_rank[i], self.total_instances)

  def output_incorrect_results(self):
    super(EvalWithRank, self).output_incorrect_results()
    for i in xrange(2, self.max_rank_for_credit + 1):
      self.output_fraction("  Incorrect, with correct at rank %s" % i,
                           self.incorrect_by_exact_rank[i],
                           self.total_instances)
    self.output_fraction("  Incorrect, with correct not in top %s" %
                           self.max_rank_for_credit,
                           self.incorrect_past_max_rank, self.total_instances)

class GeotagDocumentEval(EvalWithRank):
  def __init__(self, max_rank_for_credit=10):
    super(GeotagDocumentEval, self).__init__(max_rank_for_credit)
    self.true_dists = []
    self.degree_dists = []

  def record_result(self, rank, true_dist, degree_dist):
    super(GeotagDocumentEval, self).record_result(rank)
    self.true_dists += [true_dist]
    self.degree_dists += [degree_dist]

  def output_incorrect_results(self):
    super(GeotagDocumentEval, self).output_incorrect_results()
    self.true_dists.sort()
    self.degree_dists.sort()
    errprint("  Mean true distance to true center = %.2f" %
             mean(self.true_dists))
    errprint("  Median true distance to true center = %.2f" %
             median(self.true_dists))
    errprint("  Mean degree distance to degree center = %.2f" %
             mean(self.degree_dists))
    errprint("  Median degree distance to degree center = %.2f" %
             median(self.degree_dists))


class Results(object):
  ####### Results for geotagging toponyms

  incorrect_geotag_toponym_reasons = [
    ('incorrect_with_no_candidates',
     'Incorrect, with no candidates'),
    ('incorrect_with_no_correct_candidates',
     'Incorrect, with candidates but no correct candidates'),
    ('incorrect_with_multiple_correct_candidates',
     'Incorrect, with multiple correct candidates'),
    ('incorrect_one_correct_candidate_missing_link_info',
     'Incorrect, with one correct candidate, but link info missing'),
    ('incorrect_one_correct_candidate',
     'Incorrect, with one correct candidate'),
  ]

  # Overall statistics
  all_toponym = EvalWithCandidateList(incorrect_geotag_toponym_reasons) 

  # Statistics when toponym not same as true name of location
  diff_surface = EvalWithCandidateList(incorrect_geotag_toponym_reasons)

  # Statistics when toponym not same as true name or short form of location
  diff_short = EvalWithCandidateList(incorrect_geotag_toponym_reasons)

  @classmethod
  def record_geotag_toponym_result(cls, correct, toponym, trueloc, reason,
                                   num_arts):
    cls.all_toponym.record_result(correct, reason, num_arts)
    if toponym != trueloc:
      cls.diff_surface.record_result(correct, reason, num_arts)
      (short, div) = compute_short_form(trueloc)
      if toponym != short:
        cls.diff_short.record_result(correct, reason, num_arts)

  @classmethod
  def output_geotag_toponym_results(cls):
    errprint("Results for all toponyms:")
    cls.all_toponym.output_results()
    errprint("")
    errprint("Results for toponyms when different from true location name:")
    cls.diff_surface.output_results()
    errprint("")
    errprint("Results for toponyms when different from either true location name")
    errprint("  or its short form:")
    cls.diff_short.output_results()
    cls.output_resource_usage()

  @classmethod
  def output_resource_usage(cls):
    errprint("Total elapsed time: %s" %
             float_with_commas(get_program_time_usage()))
    errprint("Memory usage: %s" % int_with_commas(get_program_memory_usage()))

  ####### Results for geotagging documents/articles

  all_document = GeotagDocumentEval()

  # naitr = "num articles in true region"
  docs_by_naitr = TableByRange([1, 10, 25, 100], GeotagDocumentEval)

  # Results for documents where the location is at a certain distance
  # from the center of the true statistical region.  The key is measured in
  # fractions of a tiling region (determined by 'dist_fraction_increment',
  # e.g. if dist_fraction_increment = 0.25 then values in the range of
  # [0.25, 0.5) go in one bin, [0.5, 0.75) go in another, etc.).  We measure
  # distance is two ways: True distance (in miles or whatever) and "degree
  # distance", as if degrees were a constant length both latitudinally
  # and longitudinally.
  dist_fraction_increment = 0.25
  docs_by_degree_dist_to_true_center = \
      collections.defaultdict(GeotagDocumentEval)
  docs_by_true_dist_to_true_center = \
      collections.defaultdict(GeotagDocumentEval)

  # Similar, but distance between location and center of top predicted region.
  dist_fractions_for_error_dist = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8,
                                   12, 16, 24, 32, 48, 64, 96, 128, 192, 256,
                                   # We're never going to see these
                                   384, 512, 768, 1024, 1536, 2048]
  docs_by_degree_dist_to_pred_center = \
      TableByRange(dist_fractions_for_error_dist, GeotagDocumentEval)
  docs_by_true_dist_to_pred_center = \
      TableByRange(dist_fractions_for_error_dist, GeotagDocumentEval)

  true_error_dists = []
  deg_error_dists = []

  @classmethod
  def record_geotag_document_result(cls, rank, coord, pred_latind,
                                    pred_longind, num_arts_in_true_region):
    def degree_dist(c1, c2):
      return math.sqrt((c1.lat - c2.lat)**2 + (c1.long - c2.long)**2)

    predcenter = stat_region_indices_to_center_coord(pred_latind, pred_longind)
    pred_truedist = spheredist(coord, predcenter) / Opts.miles_per_region
    pred_degdist = degree_dist(coord, predcenter) / degrees_per_region

    cls.all_document.record_result(rank, pred_truedist, pred_degdist)
    naitr = cls.docs_by_naitr.get_collector(rank)
    naitr.record_result(rank, pred_truedist, pred_degdist)

    true_latind, true_longind = coord_to_stat_region_indices(coord)
    regcenter = stat_region_indices_to_center_coord(true_latind, true_longind)
    true_truedist = spheredist(coord, regcenter) / Opts.miles_per_region
    true_degdist = degree_dist(coord, regcenter) / degrees_per_region
    fracinc = cls.dist_fraction_increment
    true_truedist = fracinc * (true_truedist // fracinc)
    true_degdist = fracinc * (true_degdist // fracinc)

    cls.docs_by_true_dist_to_true_center[true_truedist]. \
        record_result(rank, pred_truedist, pred_degdist)
    cls.docs_by_degree_dist_to_true_center[true_degdist]. \
        record_result(rank, pred_truedist, pred_degdist)

    cls.docs_by_true_dist_to_pred_center.get_collector(pred_truedist). \
        record_result(rank, pred_truedist, pred_degdist)
    cls.docs_by_degree_dist_to_pred_center.get_collector(pred_degdist). \
        record_result(rank, pred_truedist, pred_degdist)

  @classmethod
  def record_geotag_document_other_stat(cls, othertype):
    cls.all_document.record_other_stat(othertype)

  @classmethod
  def output_geotag_document_results(cls, all_results=False):
    errprint("")
    errprint("Results for all documents/articles:")
    cls.all_document.output_results()
    if all_results:
      errprint("")
      for (lower, upper, obj) in cls.docs_by_naitr.iter_ranges():
        errprint("")
        errprint("Results for documents/articles where number of articles")
        errprint("  in true region is in the range [%s,%s]:" %
                 (lower, upper - 1 if type(upper) is int else upper))
        obj.output_results()
      errprint("")
      for (truedist, obj) in \
          sorted(cls.docs_by_true_dist_to_true_center.iteritems(),
                 key=lambda x:x[0]):
        lowrange = truedist * Opts.miles_per_region
        highrange = ((truedist + cls.dist_fraction_increment) *
                     Opts.miles_per_region)
        errprint("")
        errprint("Results for documents/articles where distance to center")
        errprint("  of true region in miles is in the range [%.2f,%.2f):" %
                 (lowrange, highrange))
        obj.output_results()
      errprint("")
      for (degdist, obj) in \
          sorted(cls.docs_by_degree_dist_to_true_center.iteritems(),
                 key=lambda x:x[0]):
        lowrange = degdist * degrees_per_region
        highrange = ((degdist + cls.dist_fraction_increment) *
                     degrees_per_region)
        errprint("")
        errprint("Results for documents/articles where distance to center")
        errprint("  of true region in degrees is in the range [%.2f,%.2f):" %
                 (lowrange, highrange))
        obj.output_results()
    # FIXME: Output median and mean of true and degree error dists; also
    # maybe move this info info EvalByRank so that we can output the values
    # for each category
    errprint("")
    cls.output_resource_usage()


############################################################################
#                             Main geotagging code                         #
############################################################################

# Class of word in a file containing toponyms.  Fields:
#
#   word: The identity of the word.
#   is_stop: True if it is a stopword.
#   is_toponym: True if it is a toponym.
#   coord: For a toponym with specified ground-truth coordinate, the
#          coordinate.  Else, none.
#   location: True location if given, else None.
#   context: Vector including the word and 10 words on other side.
#   document: The document (article, etc.) of the word.  Useful when a single
#             file contains multiple such documents.
#
class GeogWord(object):
  __slots__ = ['word', 'is_stop', 'is_toponym', 'coord', 'location',
               'context', 'document']

  def __init__(self, word):
    self.word = word
    self.is_stop = False
    self.is_toponym = False
    self.coord = None
    self.location = None
    self.context = None
    self.document = None

# Abstract class for reading documents from a test file and evaluating on
# them.
class TestFileEvaluator(object):
  def __init__(self, opts):
    self.opts = opts
    self.documents_processed = 0

  def yield_documents(self, filename):
    pass

  def evaluate_document(self, doc):
    # Return True if document was actually processed and evaluated; False
    # is skipped.
    return True

  def output_results(self, final=False):
    pass

  def evaluate_and_output_results(self, files):
    status = StatusMessage('document')
    last_elapsed = 0
    last_processed = 0
    for filename in files:
      errprint("Processing evaluation file %s..." % filename)
      for doc in self.yield_documents(filename):
        errprint("Processing document: %s" % doc)
        if self.evaluate_document(doc):
          new_elapsed = status.item_processed()
          new_processed = status.num_processed()
          # If five minutes and ten documents have gone by, print out results
          if (new_elapsed - last_elapsed >= 300 and
              new_processed - last_processed >= 10):
            errprint("Results after %d documents:" % status.num_processed())
            self.output_results(final=False)
            last_elapsed = new_elapsed
            last_processed = new_processed
  
    errprint("")
    errprint("Final results: All %d documents processed:" %
             status.num_processed())
    self.output_results(final=True)

class GeotagToponymStrategy(object):
  def need_context(self):
    pass

  def compute_score(self, geogword, art):
    pass

# Find each toponym explicitly mentioned as such and disambiguate it
# (find the correct geographic location) using the "link baseline", i.e.
# use the location with the highest number of incoming links.
class LinkBaselineStrategy(GeotagToponymStrategy):
  def need_context(self):
    return False

  def compute_score(self, geogword, art):
    return get_adjusted_incoming_links(art)

# Find each toponym explicitly mentioned as such and disambiguate it
# (find the correct geographic location) using Naive Bayes, possibly
# in conjunction with the baseline.
class NaiveBayesStrategy(GeotagToponymStrategy):
  def __init__(self, use_baseline):
    self.use_baseline = use_baseline

  def need_context(self):
    return True

  def compute_score(self, geogword, art):
    # FIXME FIXME!!! We are assuming that the baseline is 'internal-link',
    # regardless of its actual settings.
    thislinks = get_adjusted_incoming_links(art)

    if self.opts.naive_bayes_type == 'article':
      distobj = art.dist
    else:
      distobj = art.find_regworddist()
    totalprob = 0.0
    total_word_weight = 0.0
    if not self.strategy.use_baseline:
      word_weight = 1.0
      baseline_weight = 0.0
    elif self.opts.naive_bayes_weighting == 'equal':
      word_weight = 1.0
      baseline_weight = 1.0
    else:
      baseline_weight = self.opts.baseline_weight
      word_weight = 1 - baseline_weight
    for (dist, word) in geogword.context:
      if not Opts.preserve_case_words: word = word.lower()
      wordprob = distobj.lookup_word(word)

      # Compute weight for each word, based on distance from toponym
      if self.opts.naive_bayes_weighting == 'equal' or \
         self.opts.naive_bayes_weighting == 'equal-words':
        thisweight = 1.0
      else:
        thisweight = 1.0/(1+dist)

      total_word_weight += thisweight
      totalprob += thisweight*log(wordprob)
    if debug > 0:
      errprint("Computed total word log-likelihood as %s" % totalprob)
    # Normalize probability according to the total word weight
    if total_word_weight > 0:
      totalprob /= total_word_weight
    # Combine word and prior (baseline) probability acccording to their
    # relative weights
    totalprob *= word_weight
    totalprob += baseline_weight*log(thislinks)
    if debug > 0:
      errprint("Computed total log-likelihood as %s" % totalprob)
    return totalprob

  def need_context(self):
    return True

  def compute_score(self, geogword, art):
    return get_adjusted_incoming_links(art)

class GeotagToponymEvaluator(TestFileEvaluator):
  def __init__(self, opts, strategy):
    super(GeotagToponymEvaluator, self).__init__(opts)
    self.strategy = strategy
    
  # Given an evaluation file, read in the words specified, including the
  # toponyms.  Mark each word with the "document" (e.g. article) that it's
  # within.
  def yield_geogwords(self, filename):
    pass

  # Retrieve the words yielded by yield_geowords() and separate by "document"
  # (e.g. article); yield each "document" as a list of such Geogword objects.
  # If self.compute_context, also generate the set of "context" words used for
  # disambiguation (some window, e.g. size 20, of words around each
  # toponym).
  def yield_documents(self, filename):
    def return_word(word):
      if word.is_toponym:
        if debug > 1:
          errprint("Saw loc %s with true coordinates %s, true location %s" %
                   (word.word, word.coord, word.location))
      else:
        if debug > 2:
          errprint("Non-toponym %s" % word.word)
      return word

    for k, g in itertools.groupby(self.yield_geogwords(filename),
                                  lambda word: word.document or 'foo'):
      if k:
        errprint("Processing document %s..." % k)
      results = [return_word(word) for word in g]

      # Now compute context for words
      nbcl = Opts.naive_bayes_context_len
      if self.strategy.need_context():
        # First determine whether each word is a stopword
        for i in xrange(len(results)):
          # If a word tagged as a toponym is homonymous with a stopword, it
          # still isn't a stopword.
          results[i].is_stop = (not results[i].coord and
                                results[i].word in stopwords)
        # Now generate context for toponyms
        for i in xrange(len(results)):
          if results[i].coord:
            # Select up to Opts.naive_bayes_context_len words on either side;
            # skip stopwords.  Associate each word with the distance away from
            # the toponym.
            minind = max(0,i-nbcl)
            maxind = min(len(results),i+nbcl+1)
            results[i].context = \
              [(dist, x.word)
               for (dist, x) in
                 zip(range(i-minind, i-maxind), results[minind:maxind])
               if x.word not in stopwords]

      yield [word for word in results if word.coord]

  # Disambiguate the toponym, specified in GEOGWORD.  Determine the possible
  # locations that the toponym can map to, and call COMPUTE_SCORE on each one
  # to determine a score.  The best score determines the location considered
  # "correct".  Locations without a matching Wikipedia article are skipped.
  # The location considered "correct" is compared with the actual correct
  # location specified in the toponym, and global variables corresponding to
  # the total number of toponyms processed and number correctly determined are
  # incremented.  Various debugging info is output if 'debug' is set.
  # COMPUTE_SCORE is passed two arguments: GEOGWORD and the location to
  # compute the score of.

  def disambiguate_toponym(self, geogword):
    toponym = geogword.word
    coord = geogword.coord
    if not coord: return # If no ground-truth, skip it
    lotop = toponym.lower()
    bestscore = -1e308
    bestart = None
    articles = ArticleTable.lower_toponym_to_article[lotop]
    locs = (Gazetteer.lower_toponym_to_location[lotop] +
            Gazetteer.lower_toponym_to_division[lotop])
    for loc in locs:
      if loc.match and loc.match not in articles:
        articles += [loc.match]
    if not articles:
      if debug > 0:
        errprint("Unable to find any possibilities for %s" % toponym)
      correct = False
    else:
      if debug > 0:
        errprint("Considering toponym %s, coordinates %s" %
                 (toponym, coord))
        errprint("For toponym %s, %d possible articles" %
                 (toponym, len(articles)))
      for art in articles:
        if debug > 0:
            errprint("Considering article %s" % art)
        if not art:
          if debug > 0:
            errprint("--> Location without matching article")
          continue
        else:
          thisscore = self.strategy.compute_score(geogword, art)
        if thisscore > bestscore:
          bestscore = thisscore
          bestart = art 
      if bestart:
        correct = bestart.matches_coord(coord)
      else:
        correct = False

    num_arts = len(articles)

    if correct:
      reason = None
    else:
      if num_arts == 0:
        reason = 'incorrect_with_no_candidates'
      else:
        good_arts = [art for art in articles if art.matches_coord(coord)]
        if not good_arts:
          reason = 'incorrect_with_no_correct_candidates'
        elif len(good_arts) > 1:
          reason = 'incorrect_with_multiple_correct_candidates'
        else:
          goodart = good_arts[0]
          if goodart.incoming_links is None:
            reason = 'incorrect_one_correct_candidate_missing_link_info'
          else:
            reason = 'incorrect_one_correct_candidate'

    errprint("Eval: Toponym %s (true: %s at %s),"
             % (toponym, geogword.location, coord), nonl=True)
    if correct:
      errprint("correct")
    else:
      errprint("incorrect, reason = %s" % reason)

    Results.record_geotag_toponym_result(correct, toponym, geogword.location,
                                         reason, num_arts)

    if debug > 0 and bestart:
      errprint("Best article = %s, score = %s, dist = %s, correct %s"
               % (bestart, bestscore, bestart.distance_to_coord(coord),
                  correct))

  def evaluate_document(self, doc):
    for geogword in doc:
       self.disambiguate_toponym(geogword)
    return True

  def output_results(self, final=False):
    Results.output_geotag_toponym_results()


def get_adjusted_incoming_links(art):
  thislinks = art.incoming_links
  if thislinks is None:
    thislinks = 0
    if debug > 0:
      warning("Strange, %s has no link count" % art)
  else:
    if debug > 0:
      errprint("--> Link count is %s" % thislinks)
  if thislinks == 0: # Whether from unknown count or count is actually zero
    thislinks = 0.01 # So we don't get errors from log(0)
  return thislinks

class TRCoNLLGeotagToponymEvaluator(GeotagToponymEvaluator):
  # Read a file formatted in TR-CONLL text format (.tr files).  An example of
  # how such files are fomatted is:
  #
  #...
  #...
  #last    O       I-NP    JJ
  #week    O       I-NP    NN
  #&equo;s O       B-NP    POS
  #U.N.    I-ORG   I-NP    NNP
  #Security        I-ORG   I-NP    NNP
  #Council I-ORG   I-NP    NNP
  #resolution      O       I-NP    NN
  #threatening     O       I-VP    VBG
  #a       O       I-NP    DT
  #ban     O       I-NP    NN
  #on      O       I-PP    IN
  #Sudanese        I-MISC  I-NP    NNP
  #flights O       I-NP    NNS
  #abroad  O       I-ADVP  RB
  #if      O       I-SBAR  IN
  #Khartoum        LOC
  #        >c1     NGA     15.5833333      32.5333333      Khartoum > Al Khar<BA>om > Sudan
  #        c2      NGA     -17.8833333     30.1166667      Khartoum > Zimbabwe
  #        c3      NGA     15.5880556      32.5341667      Khartoum > Al Khar<BA>om > Sudan
  #        c4      NGA     15.75   32.5    Khartoum > Al Khar<BA>om > Sudan
  #does    O       I-VP    VBZ
  #not     O       I-NP    RB
  #hand    O       I-NP    NN
  #over    O       I-PP    IN
  #three   O       I-NP    CD
  #men     O       I-NP    NNS
  #...
  #...
  #
  # Yield GeogWord objects, one per word.
  def yield_geogwords(self, filename):
    in_loc = False
    for line in uchompopen(filename, errors='replace'):
      try:
        (word, ty) = re.split('\t', line, 1)
        if word:
          if in_loc:
            in_loc = False
            yield wordstruct
          wordstruct = GeogWord(word)
          wordstruct.document = filename
          if ty.startswith('LOC'):
            in_loc = True
            wordstruct.is_toponym = True
          else:
            yield wordstruct
        elif in_loc and ty[0] == '>':
          (off, gaz, lat, long, fulltop) = re.split('\t', ty, 4)
          lat = float(lat)
          long = float(long)
          wordstruct.coord = Coord(lat, long)
          wordstruct.location = fulltop
      except Exception, exc:
        errprint("Bad line %s" % line)
        errprint("Exception is %s" % exc)
        if type(exc) is not ValueError:
          traceback.print_exc()
    if in_loc:
      yield wordstruct

class WikipediaGeotagToponymEvaluator(GeotagToponymEvaluator):
  def yield_geogwords(self, filename):
    title = None
    for line in uchompopen(filename, errors='replace'):
      if rematch('Article title: (.*)$', line):
        title = m_[1]
      elif rematch('Link: (.*)$', line):
        args = m_[1].split('|')
        trueart = args[0]
        linkword = trueart
        if len(args) > 1:
          linkword = args[1]
        word = GeogWord(linkword)
        word.is_toponym = True
        word.location = trueart
        word.document = title
        art = ArticleTable.lookup_article(trueart)
        if art:
          word.coord = art.coord
        yield word
      else:
        word = GeogWord(line)
        word.document = title
        yield word


class GeotagDocumentStrategy(object):
  def return_ranked_regions(self, worddist):
    pass

class KLDivergenceStrategy(object):
  def __init__(self, partial=True):
    self.partial = partial

  def return_ranked_regions(self, worddist):
    article_pq = PriorityQueue()
    for stat_region in StatRegion.yield_all_nonempty_regions():
      inds = (stat_region.latind, stat_region.longind)
      if debug > 1:
        (latind, longind) = inds
        coord = region_indices_to_coord(latind, longind)
        errprint("Nonempty region at indices %s,%s = coord %s, num_articles = %s"
                 % (latind, longind, coord, stat_region.worddist.num_arts))
      kldiv = fast_kl_divergence(worddist, stat_region.worddist,
                                 partial=self.partial)
      #kldiv = article.dist.test_kl_divergence(stat_region.worddist,
      #                           partial=self.partial)
      #errprint("For region %s, KL divergence = %s" % (inds, kldiv))
      article_pq.add_task(kldiv, stat_region)

    regions = []
    while True:
      try:
        regions.append(article_pq.get_top_priority())
      except IndexError:
        break
    return regions


class PerWordRegionDistributionsStrategy(object):
  def return_ranked_regions(self, worddist):
    regdist = RegionDist.get_region_dist_for_word_dist(worddist)
    return [reg for (reg, prob) in sorted(regdist.regionprobs.iteritems(),
                                          key=lambda x:x[1], reverse=True)]


class GeotagDocumentEvaluator(TestFileEvaluator):
  def __init__(self, opts, strategy):
    super(GeotagDocumentEvaluator, self).__init__(opts)
    self.strategy = strategy
    StatRegion.generate_all_nonempty_regions()
    errprint("Number of non-empty regions: %s" % StatRegion.num_non_empty_regions)
    errprint("Number of empty regions: %s" % StatRegion.num_empty_regions)

  def output_results(self, final=False):
    Results.output_geotag_document_results(all_results=final)


class WikipediaGeotagDocumentEvaluator(GeotagDocumentEvaluator):
  def yield_documents(self, filename):
    for art in ArticleTable.articles_by_split['dev']:
      assert art.split == 'dev'
      yield art

    #title = None
    #words = []
    #for line in uchompopen(filename, errors='replace'):
    #  if rematch('Article title: (.*)$', line):
    #    if title:
    #      yield (title, words)
    #    title = m_[1]
    #    words = []
    #  elif rematch('Link: (.*)$', line):
    #    args = m_[1].split('|')
    #    trueart = args[0]
    #    linkword = trueart
    #    if len(args) > 1:
    #      linkword = args[1]
    #    words.append(linkword)
    #  else:
    #    words.append(line)
    #if title:
    #  yield (title, words)

  def evaluate_document(self, article):
    if not article.dist:
      # This can (and does) happen when --max-time-per-stage is set,
      # so that the counts for many articles don't get read in.
      if not Opts.max_time_per_stage:
        warning("Can't evaluate article %s without distribution" % article)
      Results.record_geotag_document_other_stat('Skipped articles')
      return False
    assert article.dist.finished
    true_latind, true_longind = coord_to_stat_region_indices(article.coord)
    true_statreg = StatRegion.find_region_for_coord(article.coord)
    naitr = true_statreg.worddist.num_arts
    if debug > 0:
      errprint("Evaluating article %s with %s articles in true region" %
               (article, naitr))
    regs = self.strategy.return_ranked_regions(article.dist)
    rank = 1
    for reg in regs:
      if reg.latind == true_latind and reg.longind == true_longind:
        break
      rank += 1
    Results.record_geotag_document_result(rank, article.coord,
                                          regs[0].latind, regs[0].longind,
                                          num_arts_in_true_region=naitr)
    if naitr == 0:
      Results.record_geotag_document_other_stat('Articles with no training articles in region')
    errprint("For article %s, true region at rank %s" % (article, rank))
    return True


############################################################################
#                               Process files                              #
############################################################################

# Read in the list of stopwords from the given filename.
def read_stopwords(filename):
  errprint("Reading stopwords from %s..." % filename)
  for line in uchompopen(filename):
    stopwords.add(line)


def read_article_data(filename):
  redirects = []

  def process(art):
    if art.namespace != 'Main':
      return
    if art.redir:
      redirects.append(art)
    elif art.coord:
      ArticleTable.record_article(art.title, art)
      if art.split == 'training':
        StatRegion.add_article_to_region(art)

  read_article_data_file(filename, process, article_type=StatArticle,
                         max_time_per_stage=Opts.max_time_per_stage)

  for x in redirects:
    redart = ArticleTable.lookup_article(x.redir)
    if redart:
      ArticleTable.record_article(x.title, redart, is_redirect=True)


# Parse the result of a previous run of --output-counts and generate
# a unigram distribution for Naive Bayes matching.  We do a simple version
# of Good-Turing smoothing where we assign probability mass to unseen
# words equal to the probability mass of all words seen once, and rescale
# the remaining probabilities accordingly.

def read_word_counts(filename):

  def one_article_probs():
    if total_tokens == 0: return
    art = ArticleTable.lookup_article(title)
    if not art:
      warning("Skipping article %s, not in table" % title)
      return
    art.dist = WordDist()
    art.dist.set_word_distribution(total_tokens, wordhash, note_globally=True)

  errprint("Reading word counts from %s..." % filename)
  status = StatusMessage('article')
  total_tokens = 0

  title = None
  for line in uchompopen(filename):
    if line.startswith('Article title: '):
      m = re.match('Article title: (.*)$', line)
      if title:
        one_article_probs()
      # Stop if we've reached the maximum
      if status.item_processed() >= Opts.max_time_per_stage:
        break
      title = m.group(1)
      wordhash = intdict()
      total_tokens = 0
    elif line.startswith('Article coordinates: ') or \
        line.startswith('Article ID: '):
      pass
    else:
      m = re.match('(.*) = ([0-9]+)$', line)
      if not m:
        warning("Strange line, can't parse: title=%s: line=%s" % (title, line))
        continue
      word = m.group(1)
      if not Opts.preserve_case_words: word = word.lower()
      count = int(m.group(2))
      if word in stopwords and Opts.ignore_stopwords_in_article_dists: continue
      word = internasc(word)
      total_tokens += count
      wordhash[word] += count
  else:
    one_article_probs()

  WordDist.finish_global_distribution()
  ArticleTable.finish_article_distributions()

class Gazetteer(object):
  # For each toponym (name of location), value is a list of Locality items,
  # listing gazetteer locations and corresponding matching Wikipedia articles.
  lower_toponym_to_location = listdict()

  # For each toponym corresponding to a division higher than a locality,
  # list of divisions with this name.
  lower_toponym_to_division = listdict()

  # Table of all toponyms seen in evaluation files, along with how many times
  # seen.  Used to determine when caching of certain toponym-specific values
  # should be done.
  #toponyms_seen_in_eval_files = intdict()


class WorldGazetteer(Gazetteer):

  # Find the Wikipedia article matching an entry in the gazetteer.
  # The format of an entry is
  #
  # ID  NAME  ALTNAMES  ORIG-SCRIPT-NAME  TYPE  POPULATION  LAT  LONG  DIV1  DIV2  DIV3
  #
  # where there is a tab character separating each field.  Fields may be empty;
  # but there will still be a tab character separating the field from others.
  #
  # The ALTNAMES specify any alternative names of the location, often including
  # the equivalent of the original name without any accent characters.  If
  # there is more than one alternative name, the possibilities are separated
  # by a comma and a space, e.g. "Dongshi, Dongshih, Tungshih".  The
  # ORIG-SCRIPT-NAME is the name in its original script, if that script is not
  # Latin characters (e.g. names in Russia will be in Cyrillic). (For some
  # reason, names in Chinese characters are listed in the ALTNAMES rather than
  # the ORIG-SCRIPT-NAME.)
  #
  # LAT and LONG specify the latitude and longitude, respectively.  These are
  # given as integer values, where the actual value is found by dividing this
  # integer value by 100.
  #
  # DIV1, DIV2 and DIV3 specify different-level divisions that a location is
  # within, from largest to smallest.  Typically the largest is a country.
  # For locations in the U.S., the next two levels will be state and county,
  # respectively.  Note that such divisions also have corresponding entries
  # in the gazetteer.  However, these entries are somewhat lacking in that
  # (1) no coordinates are given, and (2) only the top-level division (the
  # country) is given, even for third-level divisions (e.g. counties in the
  # U.S.).
  #
  # For localities, add them to the region-map that covers the earth if
  # ADD_TO_REGION_MAP is true.

  @classmethod
  def match_world_gazetteer_entry(cls, line):
    # Split on tabs, make sure at least 11 fields present and strip off
    # extra whitespace
    fields = re.split(r'\t', line.strip()) + ['']*11
    fields = [x.strip() for x in fields[0:11]]
    (id, name, altnames, orig_script_name, typ, population, lat, long,
     div1, div2, div3) = fields

    # Skip places without coordinates
    if not lat or not long:
      if debug > 1:
        errprint("Skipping location %s (div %s/%s/%s) without coordinates" %
                 (name, div1, div2, div3))
      return

    # Create and populate a Locality object
    loc = Locality(name, Coord(int(lat) / 100., int(long) / 100.))
    loc.type = typ
    if altnames:
      loc.altnames = re.split(', ', altnames)
    # Add the given location to the division the location is in
    loc.div = Division.note_point_seen_in_division(loc, (div1, div2, div3))
    if debug > 1:
      errprint("Saw location %s (div %s/%s/%s) with coordinates %s" %
               (loc.name, div1, div2, div3, loc.coord))

    # Record the location.  For each name for the location (its
    # canonical name and all alternates), add the location to the list of
    # locations associated with the name.  Record the name in lowercase
    # for ease in matching.
    for name in [loc.name] + loc.altnames:
      loname = name.lower()
      if debug > 1:
        errprint("Noting lower_toponym_to_location for toponym %s, canonical name %s"
                 % (name, loc.name))
      cls.lower_toponym_to_location[loname] += [loc]

    # We start out looking for articles whose distance is very close,
    # then widen until we reach Opts.max_dist_for_close_match.
    maxdist = 5
    while maxdist <= Opts.max_dist_for_close_match:
      match = ArticleTable.find_match_for_locality(loc, maxdist)
      if match: break
      maxdist *= 2

    if not match: 
      if debug > 1:
        errprint("Unmatched name %s" % loc.name)
      return
    
    # Record the match.
    loc.match = match
    match.location = loc
    if debug > 1:
      errprint("Matched location %s (coord %s) with article %s, dist=%s"
               % (loc.name, loc.coord, match,
                  spheredist(loc.coord, match.coord)))

  # Read in the data from the World gazetteer in FILENAME and find the
  # Wikipedia article matching each entry in the gazetteer.  For localities,
  # add them to the region-map that covers the earth if ADD_TO_REGION_MAP is
  # true.
  @classmethod
  def read_world_gazetteer_and_match(cls, filename):
    errprint("Matching gazetteer entries in %s..." % filename)
    status = StatusMessage('gazetteer entry')

    # Match each entry in the gazetteer
    for line in uchompopen(filename):
      if debug > 1:
        errprint("Processing line: %s" % line)
      cls.match_world_gazetteer_entry(line)
      if status.item_processed() >= Opts.max_time_per_stage:
        break

    for division in Division.path_to_division.itervalues():
      if debug > 1:
        errprint("Processing division named %s, path %s"
                 % (division.name, division.path))
      division.compute_boundary()
      match = ArticleTable.find_match_for_division(division)
      if match:
        if debug > 1:
          errprint("Matched article %s for division %s, path %s" %
                   (match, division.name, division.path))
        division.match = match
        match.location = division
      else:
        if debug > 1:
          errprint("Couldn't find match for division %s, path %s" %
                   (division.name, division.path))

# If given a directory, yield all the files in the directory; else just
# yield the file.
def yield_directory_files(dir):
  if os.path.isdir(dir): 
    for fname in os.listdir(dir):
      fullname = os.path.join(dir, fname)
      yield fullname
  else:
    yield dir
  
# Given an evaluation file, count the toponyms seen and add to the global count
# in toponyms_seen_in_eval_files.
def count_toponyms_in_file(fname):
  def count_toponyms(geogword):
    toponyms_seen_in_eval_files[geogword.word.lower()] += 1
  process_eval_file(fname, count_toponyms, compute_context=False,
                    only_toponyms=True)

############################################################################
#                                  Main code                               #
############################################################################

class WikiDisambigProgram(NLPProgram):

  def populate_options(self, op):
    op.add_option("-t", "--gazetteer-type", type='choice', default="world",
                  choices=['world', 'db'],
                  help="""Type of gazetteer file specified using --gazetteer;
default '%default'.""")
    op.add_option("-s", "--stopwords-file",
                  help="""File containing list of stopwords.""",
                  metavar="FILE")
    op.add_option("-a", "--article-data-file",
                  help="""File containing info about Wikipedia articles.""",
                  metavar="FILE")
    op.add_option("-g", "--gazetteer-file",
                  help="""File containing gazetteer information to match.""",
                  metavar="FILE")
    op.add_option("-c", "--counts-file",
                  help="""File containing output from a prior run of
--output-counts, listing for each article the words in the article and
associated counts.""",
                  metavar="FILE")
    op.add_option("-p", "--pickle-file",
                  help="""Serialize the result of processing the word-coords
file to the given file.""",
                  metavar="FILE")
    op.add_option("-u", "--unpickle-file",
                  help="""Read the result of serializing the word-coords file
to the given file.""",
                  metavar="FILE")
    op.add_option("-e", "--eval-file",
                  help="""File or directory containing files to evaluate on.
Each file is read in and then disambiguation is performed.""",
                  metavar="FILE")
    op.add_option("-f", "--eval-format", type='choice',
                  default="wiki", choices=['tr-conll', 'wiki', 'raw-text'],
                  help="""Format of evaluation file(s).  Default '%default'.""")
    op.add_option("--preserve-case-words", action='store_true',
                  default=False,
                  help="""Don't fold the case of words used to compute and
match against article distributions.  Note that this does not apply to
toponyms; currently, toponyms are always matched case-insensitively.""")
    op.add_option("--ignore-stopwords-in-article-dists", action='store_true',
                  default=False,
                  help="""Ignore stopwords when computing word
distributions.""")
    op.add_option("--max-dist-for-close-match", type='float', default=80,
                  help="""Maximum number of miles allowed when looking for a
close match.  Default %default.""")
    op.add_option("--max-dist-for-outliers", type='float', default=200,
                  help="""Maximum number of miles allowed between a point and
any others in a division.  Points farther away than this are ignored as
"outliers" (possible errors, etc.).  Default %default.""")
    op.add_option("--naive-bayes-context-len", type='int', default=10,
                  help="""Number of words on either side of a toponym to use
in Naive Bayes matching.  Default %default.""")
    op.add_option("-m", "--mode", type='choice', default='match-only',
                  choices=['geotag-toponyms',
                           'geotag-documents',
                           'match-only', 'pickle-only'],
                  help="""Action to perform.

'match-only' means to only do the stage that involves finding matches between
gazetteer locations and Wikipedia articles (mostly useful when debugging
output is enabled).

'pickle-only' means only to generate the pickled version of the data, for
reading in by a separate process (e.g. the Java code).

'geotag-documnts' finds the proper location for each document (or article)
in the test set.

'geotag-toponyms' finds the proper location for each toponym in the test set.
The test set is specified by --eval-file.  Default '%default'.""")
    op.add_option("--geotag-toponym-strategy", type='choice',
                  default='baseline',
                  choices=['baseline',
                           'naive-bayes-with-baseline',
                           'naive-bayes-no-baseline'],
                  help="""Strategy to use for geotagging toponyms.
'baseline' means just use the baseline strategy (see --baseline-strategy);
'naive-bayes-with-baseline' means also use the words around the toponym to
be disambiguated, in a Naive-Bayes scheme, using the baseline as the prior
probability; 'naive-bayes-no-baseline' means use uniform prior probability.
Default '%default'.""")
    op.add_option("--geotag-document-strategy", type='choice',
                  default='kl-divergence',
                  choices=['baseline',
                           'kl-divergence',
                           'partial-kl-divergence',
                           'per-word-region-distributions'],
                  help="""Strategy to use for geotagging documents.
'baseline' means just use the baseline strategy (see --baseline-strategy);
'
'naive-bayes-with-baseline' means also use the words around the toponym to
be disambiguated, in a Naive-Bayes scheme, using the baseline as the prior
probability; 'naive-bayes-no-baseline' means use uniform prior probability.
Default '%default'.""")
    op.add_option("--baseline-strategy", type='choice',
                  default="internal-link",
                  choices=['internal-link', 'random', 'num-articles'],
                  help="""Strategy to use to compute the baseline.

'internal-link' means use number of internal links pointing to the article or
region.

'random' means choose randomly.

'num-articles' (only in region-type matching) means use number of articles
in region.

Default '%default'.""")
    op.add_option("--baseline-weight", type='float', metavar="WEIGHT",
                  default=0.5,
                  help="""Relative weight to assign to the baseline (prior
probability) when doing weighted Naive Bayes.  Default %default.""")
    op.add_option("--naive-bayes-weighting", type='choice',
                  default="equal",
                  choices=['equal', 'equal-words', 'distance-weighted'],
                  help="""Strategy for weighting the different probabilities
that go into Naive Bayes.  If 'equal', do pure Naive Bayes, weighting the
prior probability (baseline) and all word probabilities the same.  If
'equal-words', weight all the words the same but weight the baseline
according to --baseline-weight, assigning the remainder to the words.  If
'distance-weighted', use the --baseline-weight for the prior probability
and weight the words according to distance from the toponym.""")
    op.add_option("--width-of-stat-region", type='int', default=1,
                  help="""Width of the region used to compute a statistical
distribution for geotagging purposes, in terms of number of tiling regions.
Default %default.""")
    op.add_option("--degrees-per-region", type='float', default=None,
                  help="""Size (in degrees) of the tiling regions that cover
the earth.  Some number of tiling regions are put together to form the region
used to construct a statistical distribution.  No default; the default of
'--miles-per-region' is used instead.""")
    op.add_option("-r", "--miles-per-region", type='float', default=100.0,
                  help="""Size (in miles) of the tiling regions that cover
the earth.  Some number of tiling regions are put together to form the region
used to construct a statistical distribution.  Default %default.""")
    op.add_option("-b", "--naive-bayes-type", type='choice',
                  default="round-region",
                  choices=['article', 'round-region', 'square-region'],
                  help="""Type of context used when doing Naive Bayes
disambiguation. 'article' means use only the words in the article itself.
'round-region' means to use a region of constant radius centered on the
article's location. 'square-region' means to use a "square" region
approximately centered on the article's location. ("Square" is a misnomer
because it actually works by dividing the earth into regions of constant
latitude and longitude; as a result, the width of the regions gets
smaller as the latitude moves away from the equator. In addition,
for "square" regions, the region boundaries are fixed rather than
corresponding to a region properly centered on a location.) In
addition, when the article itself refers to a region rather than a
locality, both region-based methods use the articles which are
specified in the gazetteer to belong to the region, rather than any
particular-sized region.  Default '%default'.""")

  def implement_main(self, opts, op, args):
    global Opts
    Opts = opts
    global debug
    if opts.debug:
      debug = int(opts.debug)
      WordDist.set_debug_level(debug)
   
    # FIXME! Can only currently handle World-type gazetteers.
    if opts.gazetteer_type != 'world':
      op.error("Currently can only handle world-type gazetteers")

    if opts.miles_per_region <= 0:
      op.error("Miles per region must be positive")
    global degrees_per_region
    if opts.degrees_per_region:
      degrees_per_region = opts.degrees_per_region
    else:
      degrees_per_region = opts.miles_per_region / miles_per_degree
    global maximum_latind, minimum_latind, maximum_longind, minimum_longind
    maximum_latind, maximum_longind = \
      coord_to_tiling_region_indices(Coord(maximum_latitude,
                                           maximum_longitude))
    minimum_latind, minimum_longind = \
      coord_to_tiling_region_indices(Coord(minimum_latitude,
                                           minimum_longitude))

    if opts.width_of_stat_region <= 0:
      op.error("Width of statistical region must be positive")

    ### Start reading in the files and operating on them ###

    if opts.mode == 'pickle-only' or opts.mode.startswith('geotag'):
      self.need('stopwords_file')
      read_stopwords(opts.stopwords_file)
      if (opts.mode == 'geotag-toponyms' and
          opts.geotag_toponym_strategy == 'baseline'):
        pass
      elif not opts.unpickle_file and not opts.counts_file:
        op.error("Must specify either unpickle file or counts file")

    if opts.mode != 'pickle-only':
      self.need('gazetteer_file')

    if opts.eval_format == 'raw-text':
      # FIXME!!!!
      op.error("Raw-text reading not implemented yet")

    if opts.mode == 'geotag-documents' and opts.eval_format == 'wiki':
      pass # No need for evaluation file, uses the counts file
    # FIXME!! Fix this limitation.  Should allow raw text files.
    elif opts.mode == 'geotag-documents' and opts.eval_format != 'wiki':
      op.error("Can only geotag articles in Wikipedia format")
    elif opts.mode.startswith('geotag'):
      self.need('eval_file', 'evaluation file(s)')

    if opts.mode == 'pickle-only':
      if not opts.pickle_file:
        self.need('pickle_file')

    self.need('article_data_file')
    read_article_data(opts.article_data_file)

    #errprint("Processing evaluation file(s) %s for toponym counts..." % opts.eval_file)
    #process_dir_files(opts.eval_file, count_toponyms_in_file)
    #errprint("Number of toponyms seen: %s" % len(toponyms_seen_in_eval_files))
    #errprint("Number of toponyms seen more than once: %s" % \
    #  len([foo for (foo,count) in toponyms_seen_in_eval_files.iteritems() if
    #       count > 1]))
    #output_reverse_sorted_table(toponyms_seen_in_eval_files,
    #                            outfile=sys.stderr)

    # Read in (or unpickle) and maybe pickle the words-counts file
    if opts.mode == 'pickle-only' or opts.mode.startswith('geotag'):
      if opts.unpickle_file:
        global article_probs
        infile = open(opts.unpickle_file)
        #FIXME: article_probs = cPickle.load(infile)
        infile.close()
      elif opts.counts_file:
        read_word_counts(opts.counts_file)
      if opts.pickle_file:
        outfile = open(opts.pickle_file, "w")
        #FIXME: cPickle.dump(article_probs, outfile)
        outfile.close()

    if opts.mode == 'pickle-only': return

    WorldGazetteer.read_world_gazetteer_and_match(opts.gazetteer_file)

    if opts.mode == 'match-only': return

    if opts.mode == 'geotag-toponyms':
      # Generate strategy object
      if opts.geotag_toponym_strategy == 'baseline':
        if opts.baseline_strategy == 'internal-link':
          strategy = LinkBaselineStrategy()
        else:
          # FIXME!!!!!
          op.error("Non-internal-link baseline strategies not implemented")
      elif opts.geotag_toponym_strategy == 'naive-bayes-no-baseline':
        strategy = NaiveBayesStrategy(use_baseline=False)
      else:
        strategy = NaiveBayesStrategy(use_baseline=True)

      # Generate reader object
      if opts.eval_format == 'tr-conll':
        evalobj = TRCoNLLGeotagToponymEvaluator(opts, strategy)
      else:
        evalobj = WikipediaGeotagToponymEvaluator(opts, strategy)
    else:
      if opts.geotag_document_strategy == 'baseline':
        assert False # FIXME
      elif opts.geotag_document_strategy == 'per-word-region-distributions':
        strategy = PerWordRegionDistributionsStrategy()
      else:
        partial = opts.geotag_document_strategy == 'partial-kl-divergence'
        strategy = KLDivergenceStrategy(partial=partial)
      evalobj = WikipediaGeotagDocumentEvaluator(opts, strategy)
      # Hack: When running in --mode=geotag-documents and --eval-format=wiki,
      # we don't need an eval file because we use the article counts we've
      # already loaded.  But we will get an error if we don't set this to
      # a file.
      if not opts.eval_file:
        opts.eval_file = opts.article_data_file

    errprint("Processing evaluation file/dir %s..." % opts.eval_file)
    evalobj.evaluate_and_output_results(yield_directory_files(opts.eval_file))

WikiDisambigProgram()
