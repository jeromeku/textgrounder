///////////////////////////////////////////////////////////////////////////////
//  Copyright (C) 2011 Ben Wing, The University of Texas at Austin
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.
///////////////////////////////////////////////////////////////////////////////

package opennlp.textgrounder.geolocate

import math._
import collection.mutable

import com.codahale.trove.{mutable => trovescala}

import opennlp.textgrounder.util.collectionutil._
import opennlp.textgrounder.util.ioutil.{errprint, warning, FileHandler}
import opennlp.textgrounder.util.MeteredTask
import opennlp.textgrounder.util.osutil.output_resource_usage

import GeolocateDriver.Params
import GeolocateDriver.Debug._
import WordDist.memoizer._

// val use_sorted_list = false

//////////////////////////////////////////////////////////////////////////////
//                             Word distributions                           //
//////////////////////////////////////////////////////////////////////////////

/**
 * A class for "memoizing" words, i.e. mapping them to some other type
 * (e.g. Int) that should be faster to compare and potentially require
 * less space.
 */
abstract class Memoizer {
  /**
   * The type of a memoized word.
   */
  type Word
  /**
   * Map a word as a string to its memoized form.
   */
  def memoize_word(word: String): Word
  /**
   * Map a word from its memoized form back to a string.
   */
  def unmemoize_word(word: Word): String

  /**
   * The type of a mutable map from memoized words to Ints.
   */
  type WordIntMap
  /**
   * Create a mutable map from memoized words to Ints.
   */
  def create_word_int_map(): WordIntMap
  /**
   * The type of a mutable map from memoized words to Doubles.
   */
  type WordDoubleMap
  /**
   * Create a mutable map from memoized words to Doubles.
   */
  def create_word_double_map(): WordDoubleMap
}

/**
 * The memoizer we actually use.  Maps word strings to Ints.  Uses Trove
 * for extremely fast and memory-efficient hash tables, making use of the
 * Trove-Scala interface for easy access to the Trove hash tables.
 */
object IntStringMemoizer extends Memoizer {
  type Word = Int
  val invalid_word: Word = 0

  protected var next_word_count: Word = 1

  // For replacing strings with ints.  This should save space on 64-bit
  // machines (string pointers are 8 bytes, ints are 4 bytes) and might
  // also speed lookup.
  protected val word_id_map = mutable.Map[String,Word]()

  // Map in the opposite direction.
  protected val id_word_map = mutable.Map[Word,String]()

  def memoize_word(word: String) = {
    val index = word_id_map.getOrElse(word, 0)
    if (index != 0) index
    else {
      val newind = next_word_count
      next_word_count += 1
      word_id_map(word) = newind
      id_word_map(newind) = word
      // debprint("Memoizing word %s to ID %s", word, newind)
      newind
    }
  }

  def unmemoize_word(word: Word) = {
//    if (!(id_word_map contains word)) {
//      debprint("Can't find ID %s in id_word_map", word)
//      debprint("Word map:")
//      var its = id_word_map.toList.sorted
//      for ((key, value) <- its)
//        debprint("%s = %s", key, value)
//    }
    id_word_map(word)
  }

  def create_word_int_map() = trovescala.IntIntMap()
  type WordIntMap = trovescala.IntIntMap
  def create_word_double_map() = trovescala.IntDoubleMap()
  type WordDoubleMap = trovescala.IntDoubleMap
}

/**
 * A memoizer for testing that doesn't actually do anything -- the memoized
 * words are also strings.  This tests that we don't make any assumptions
 * about memoized words being Ints.
 */
object IdentityMemoizer extends Memoizer {
  type Word = String
  val invalid_word: Word = null
  def memoize_word(word: String): Word = word
  def unmemoize_word(word: Word): String = word

  type WordIntMap = mutable.Map[Word, Int]
  def create_word_int_map() = intmap[Word]()
  type WordDoubleMap = mutable.Map[Word, Double]
  def create_word_double_map() = doublemap[Word]()
}

/**
 * A trivial version of a memoizer to Ints that always returns the same Int.
 * Not useful as an implementation but useful for testing that code using
 * the memoizer compiles correctly, even if the normal IntStringMemoizer
 * is broken (e.g. being modified?).
 */
object TrivialIntMemoizer extends Memoizer {
  type Word = Int
  val invalid_word: Word = 0
  def memoize_word(word: String): Word = 1
  def unmemoize_word(word: Word): String = "foo"

  type WordIntMap = IntStringMemoizer.WordIntMap
  def create_word_int_map() = IntStringMemoizer.create_word_int_map()
  type WordDoubleMap = IntStringMemoizer.WordDoubleMap
  def create_word_double_map() = IntStringMemoizer.create_word_double_map()
}

/**
 * A trait that adds an implementation of `#kl_divergence` in terms of
 * a slow version with debugging info and a fast version, and optionally
 * compares the two.
 */
trait FastSlowKLDivergence {
  /**
   * This is a basic implementation of the computation of the KL-divergence
   * between this distribution and another distribution, including possible
   * debug information.  Useful for checking against the other, faster
   * implementation in `fast_kl_divergence'.
   * 
   * @param xother The other distribution to compute against.
   * @param partial If true, only compute the contribution involving words
   *   that exist in our distribution; otherwise we also have to take into
   *   account words in the other distribution even if we haven't seen them,
   *   and often also (esp. in the presence of smoothing) the contribution
   *   of all other words in the vocabulary.
   * @param return_contributing_words If true, return a map listing
   *   the words in both distributions (or, for a partial KL-divergence,
   *   the words in our distribution) and the amount of total KL-divergence
   *   they compute, useful for debugging.
   *   
   * @returns A tuple of (divergence, word_contribs) where the first
   *   value is the actual KL-divergence and the second is the map
   *   of word contributions as described above; will be null if
   *   not requested.
   */
  def slow_kl_divergence_debug(xother: WordDist, partial: Boolean = false,
      return_contributing_words: Boolean = false):
      (Double, collection.Map[Word, Double])

  /**
   * Compute the KL-divergence using the "slow" algorithm of
   * `slow_kl_divergence_debug`, but without requesting or returning debug
   * info.
   */
  def slow_kl_divergence(other: WordDist, partial: Boolean = false) = {
    val (kldiv, contribs) = slow_kl_divergence_debug(other, partial, false)
    kldiv
  }

  /**
   * A fast, optimized implementation of KL-divergence.  See the discussion in
   * `slow_kl_divergence_debug`.
   */
  def fast_kl_divergence(other: WordDist, partial: Boolean = false): Double

  /**
   * Check fast and slow KL-divergence versions against each other.
   */
  def test_kl_divergence(other: WordDist, partial: Boolean = false) = {
    val slow_kldiv = slow_kl_divergence(other, partial)
    val fast_kldiv = fast_kl_divergence(other, partial)
    if (abs(fast_kldiv - slow_kldiv) > 1e-8) {
      errprint("Fast KL-div=%s but slow KL-div=%s", fast_kldiv, slow_kldiv)
      assert(fast_kldiv == slow_kldiv)
    }
    fast_kldiv
  }

  /**
   * The actual kl_divergence implementation.  The value `test_kldiv`
   * below can be set to true to compare fast and slow against either
   * other, throwing an assertion failure if they are more than a very
   * small amount different (the small amount rather than 0 to account for
   * possible rounding error).
   */
  def kl_divergence(other: WordDist, partial: Boolean = false) = {
    val test_kldiv = false
    if (test_kldiv)
      test_kl_divergence(other, partial)
    else
      fast_kl_divergence(other, partial)
  }
}

/**
 * A factory object for WordDists (word distributions).  Currently, there is
 * only one factory object (i.e. it's a singleton), but the particular
 * factory used depends on a command-line parameter.
 */
abstract class WordDistFactory {
  /**
   * Create an empty word distribution.  Distributions created this way
   * are not meant to be added to the global word-distribution statistics
   * (see below).
   */
  def create_word_dist(): WordDist

  /**
   * Compute any global word-distribution statistics, e.g. tables for
   * doing back-off.  This is called after all of the relevant WordDists
   * have been created.  In practice, the "relevant" distributions are those
   * associated with training documents, which are read in
   * during `read_word_counts`.
   */
  def finish_global_distribution()

  /**
   * Read word counts from a file containing the counts for a set of
   * documents, create WordDists for each such document and set the
   * document's distribution to the newly-created WordDist.  Note that
   * typically the word-counts file is created by 'processwiki.py' in the
   * 'python' directory.  Generally, the format of the file is dependent
   * on the particular WordDist implementation.
   *
   * @param table Table holding all of the documents.
   * @param filehand File-handler object, which knows how to read data
   *   from files.
   * @param filename Name of file holding word counts.
   * @param stopwords List of stopwords (words to be ignored when creating
   *   a distribution).
   */
  def read_word_counts(table: DistDocumentTable,
    filehand: FileHandler, filename: String, stopwords: Set[String])
}

/**
 * A handler for one common way of reading word distributions from a file.
 */ 
trait WordDistReader {
  var task: MeteredTask = _

  /**
   * Set the word distribution of a document.  Return whether a word
   * distribution was actually created/set.
   *
   * @param doc Document to set the distribution of.
   * @param is_training_set True if this document is in the training set.
   * @param is_eval_set True if this document is in the eval set (either
   *   "dev" or "test", depending on user settings).  Generally, documents
   *   in neither the training nor eval sets should not have their
   *   word distributions set, since these distributions won't be used.
   *   In addition, documents not in the training set should not contribute
   *   to any global (e.g. back-off) statistics of the word distribution.
   * @return Whether a word distribution was actually created/set.
   */
  def set_word_dist(doc: DistDocument, is_training_set: Boolean,
      is_eval_set: Boolean): Boolean

  /**
   * Actually do the word-count reading.  This should read each document
   * in turn, set field variables appropriately to store the document's
   * properties, and call handle_one_document().  This in turn will
   * call set_word_dist() as necessary, in order to set the document's
   * word distribution.  Note that handle_one_document() returns true
   * if document reading should continue, false if it should stop.
   * In the latter case, your document-parsing code should stop and not
   * read any more documents.
   *
   * @param table Table holding all of the documents.
   * @param filehand File-handler object, which knows how to read data
   *   from files.
   * @param filename Name of file holding word counts.
   * @param stopwords List of stopwords (words to be ignored when creating
   *   a distribution).
   */
  def do_read_word_counts(table: DistDocumentTable,
      filehand: FileHandler, filename: String, stopwords: Set[String])

  /**
   * Handle one document, after its word counts (or whatever similar values
   * are needed to create its distribution) have been read in.  Return
   * true if document reading should continue, false if it should stop.
   * This is meant to be called from the implementation of
   * `do_read_word_counts`.
   *
   * @param table Document table, as passed into `do_read_word_counts`.
   * @param title Title of document.
   */
  def handle_one_document(table: DistDocumentTable, title: String) = {
    val doc = table.lookup_document(title)
    if (doc == null) {
      warning("Skipping document %s, not in table", title)
      table.num_documents_with_word_counts_but_not_in_table += 1
    } else {
      // Now set the distribution on the document; but don't use the test set's
      // distributions in computing global smoothing values and such.
      val is_training_set = (doc.split == "training")
      val is_eval_set = (doc.split == Params.eval_set)
      val dist_set = set_word_dist(doc, is_training_set, is_eval_set)
      if (dist_set)
        table.num_word_count_documents_by_split(doc.split) += 1
    }

    // Stop if we've reached the maximum
    var should_stop = false
    if (task.item_processed(maxtime = Params.max_time_per_stage))
      should_stop = true
    if ((Params.num_training_docs > 0 &&
      task.num_processed >= Params.num_training_docs)) {
      errprint("")
      errprint("Stopping because limit of %s documents reached",
        Params.num_training_docs)
      should_stop = true
    }
    !should_stop
  }

  def read_word_counts(table: DistDocumentTable,
      filehand: FileHandler, filename: String, stopwords: Set[String]) {

    task = new MeteredTask("document", "reading distributions of")

    do_read_word_counts(table, filehand, filename, stopwords)

    task.finish()
    table.num_documents_with_word_counts += task.num_processed
    output_resource_usage()
  }
}

object WordDist {
  /**
   * Object describing how we memoize words (i.e. convert them to Int
   * indices, for faster operations on them).
   */
  val memoizer = IntStringMemoizer

  /**
   * Total number of word types seen (size of vocabulary)
   */
  var total_num_word_types = 0

  /**
   * Total number of word tokens seen
   */
  var total_num_word_tokens = 0
}

/**
 * A word distribution, i.e. a statistical distribution over words in
 * a document, cell, etc.
 */
abstract class WordDist {
  /** Number of word tokens seen in the distribution. */
  var num_word_tokens: Int

  /**
   * Number of word types seen in the distribution
   * (i.e. number of different vocabulary items seen).
   */
  def num_word_types: Int
  
  /**
   * Whether we have finished computing the distribution, and therefore can
   * reliably do probability lookups.
   */
  var finished = false

  /**
   * Incorporate a document into the distribution.
   */
  def add_document(words: Traversable[String], ignore_case: Boolean = true,
      stopwords: Set[String] = Set[String]())

  /**
   * Incorporate the given distribution into our distribution.
   */
  def add_word_distribution(worddist: WordDist)

  /**
   * Partly finish computation of distribution.  This is called when the
   * distribution has been completely populated with words, and no more
   * modifications (e.g. incorporation of words or other distributions) will
   * be made to the distribution.  It should do any additional changes that
   * depend on the distribution being complete, but which do not depend on
   * the global word-distribution statistics having been computed. (These
   * statistics can be computed only after *all* word distributions that
   * are used to create these global statistics have been completely
   * populated.)
   *
   * @seealso #finish_after_global()
   * 
   * @param minimum_word_count If greater than zero, eliminate words seen
   * less than this number of times.
   */
  def finish_before_global(minimum_word_count: Int = 0)

  /**
   * Completely finish computation of the word distribution.  This is called
   * after finish_global_distribution() on the factory method, and can be
   * used to compute values for the distribution that depend on the
   * global word-distribution statistics.
   */
  def finish_after_global()

  /**
   * Finish computation of distribution.  This is intended for word
   * distributions that do not contribute to the global word-distribution
   * statistics, and which have been created after those statistics have
   * already been completed. (Examples of such distributions are the
   * distributions of grid cells and of test documents.)
   */
  def finish(minimum_word_count: Int = 0) {
    finish_before_global(minimum_word_count)
    finish_after_global()
  }

  /**
   * Compute the KL-divergence between this distribution and another
   * distribution.
   * 
   * @param other The other distribution to compute against.
   * @param partial If true, only compute the contribution involving words
   *   that exist in our distribution; otherwise we also have to take
   *   into account words in the other distribution even if we haven't
   *   seen them, and often also (esp. in the presence of smoothing) the
   *   contribution of all other words in the vocabulary.
   *   
   * @return The KL-divergence value.
   */
  def kl_divergence(other: WordDist, partial: Boolean = false): Double

  /**
   * Compute the symmetric KL-divergence between two distributions by averaging
   * the respective one-way KL-divergences in each direction.
   * 
   * @partial Same as in `kl_divergence`.
   */
  def symmetric_kldiv(other: WordDist, partial: Boolean = false) = {
    0.5*this.kl_divergence(other, partial) +
    0.5*this.kl_divergence(other, partial)
  }

  /**
   * Implementation of the cosine similarity between this and another
   * distribution, using either unsmoothed or smoothed probabilities.
   *
   * @param partial Same as in `kl_divergence`.
   * @param smoothed If true, use smoothed probabilities, if smoothing exists;
   *   otherwise, do unsmoothed.
   */
  def cosine_similarity(other: WordDist, partial: Boolean = false,
    smoothed: Boolean = false): Double

  /**
   * For a document described by its distribution 'worddist', return the
   * log probability log p(worddist|other worddist) using a Naive Bayes
   * algorithm.
   *
   * @param worddist Distribution of document.
   */
  def get_nbayes_logprob(worddist: WordDist): Double

  /**
   * Return the probabilitiy of a given word in the distribution.
   * FIXME: Should be moved into either UnigramWordDist or a new
   * UnigramLikeWordDist, since for N-grams we really want the whole N-gram,
   * and for some language models this type of lookup makes no sense at all. 
   */
  def lookup_word(word: Word): Double
  
  /**
   * Look for the most common word matching a given predicate.
   * @param pred Predicate, passed the raw (unmemoized) form of a word.
   *   Should return true if a word matches.
   * @returns Most common word matching the predicate (wrapped with
   *   Some()), or None if no match.
   * 
   * FIXME: Probably should be moved similar to `lookup_word`.
   */
  def find_most_common_word(pred: String => Boolean): Option[Word] 
}
