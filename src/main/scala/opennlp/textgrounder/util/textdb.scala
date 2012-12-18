///////////////////////////////////////////////////////////////////////////////
//  textdb.scala
//
//  Copyright (C) 2012 Ben Wing, The University of Texas at Austin
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

package opennlp.textgrounder
package util

import scala.collection.mutable
import scala.util.control.Breaks._

import java.io.PrintStream

import print.{errprint, warning}
import io._

/**
 * Package for databases stored in "textdb" format.
 * The database has the following format:
 *
 * (1) The documents are stored as field-text files, separated by a TAB
 *     character.
 * (2) There is a corresponding schema file, which lists the names of
 *     each field, separated by a TAB character, as well as any
 *     "fixed" fields that have the same value for all rows (one per
 *     line, with the name, a TAB, and the value).
 * (3) The document and schema files are identified by a suffix.
 *     The document files are named `DIR/PREFIX-SUFFIX.txt`
 *     (or `DIR/PREFIX-SUFFIX.txt.bz2` or similar, for compressed files),
 *     while the schema file is named `DIR/PREFIX-SUFFIX-schema.txt`.
 *     The SUFFIX typically specifies the category of corpus being
 *     read (e.g. "text" for corpora containing text or "unigram-counts"
 *     for a corpus containing unigram counts).  The directory is specified
 *     in a particular call to `process_files` or `read_schema_from_textdb`.
 *     The prefix is arbitrary and descriptive -- i.e. any files in the
 *     appropriate directory and with the appropriate suffix, regardless
 *     of prefix, will be loaded.  The prefix of the currently-loading
 *     document file is available though the field `current_document_prefix`.
 *
 * The most common setup is to have the schema file and any document files
 * placed in the same directory, although it's possible to have them in
 * different directories or to have document files scattered across multiple
 * directories.  Note that the naming of the files allows for multiple
 * document files in a single directory, as well as multiple corpora to
 * coexist in the same directory, as long as they have different suffixes.
 * This is often used to present different "views" onto the same corpus
 * (e.g. one containing raw text, one containing unigram counts, etc.), or
 * different splits (e.g. training vs. dev vs. test). (In fact, it is
 * common to divide a corpus into sub-corpora according to the split.
 * In such a case, document files will be named `DIR/PREFIX-SPLIT-SUFFIX.txt`
 * or similar.  This allows all files for all splits to be located using a
 * suffix consisting only of the final "SUFFIX" part, while a particular
 * split can be located using a larger prefix of the form "SPLIT-SUFFIX".)
 *
 * There are many functions in `TextDBProcessor` for reading from textdb
 * databases.  Most generally, a schema needs to be read and then the data
 * files read; both are located according to the suffix described above.
 * However, there are a number of convenience functions for handling
 * common situations (e.g. all files in a single directory).
 */
package object textdb {
  /**
   * An object describing a textdb schema, i.e. a description of each of the
   * fields in a textdb, along with "fixed fields" containing the same
   * value for every row.
   *
   * @param fieldnames List of the name of each field
   * @param fixed_values Map specifying additional fields possessing the
   *   same value for every row.  This is optional, but usually at least
   *   the "corpus-name" field should be given, with the name of the corpus
   *   (currently used purely for identification purposes).
   * @param split_text Text used for separating field values in a row;
   *   normally a tab character. (FIXME: There may be dependencies elsewhere
   *   on the separator being a tab, e.g. in EncodeDecode.)
   */
  class Schema(
    val fieldnames: Iterable[String],
    val fixed_values: Map[String, String] = Map[String, String](),
    val split_text: String = "\t"
  ) {

    import Serializer._

    val split_re = "\\Q" + split_text + "\\E"
    val field_indices = fieldnames.zipWithIndex.toMap

    def check_values_fit_schema(fieldvals: Iterable[String]) {
      if (fieldvals.size != fieldnames.size)
        throw FileFormatException(
          "Wrong-length line, expected %d fields, found %d: %s" format (
            fieldnames.size, fieldvals.size, fieldvals))
    }

    def get_value[T : Serializer](fieldvals: IndexedSeq[String],
        key: String): T = {
      get_x[T](get_field(fieldvals, key))
    }

    def get_value_if[T : Serializer](fieldvals: IndexedSeq[String],
        key: String): Option[T] = {
      get_field_if(fieldvals, key) flatMap { x => get_x_or_none[T](x) }
    }

    def get_value_or_else[T : Serializer](fieldvals: IndexedSeq[String],
        key: String, default: T): T = {
      get_value_if[T](fieldvals, key) match {
        case Some(x) => x
        case None => default
      }
    }

    def get_field(fieldvals: IndexedSeq[String], key: String) = {
      check_values_fit_schema(fieldvals)
      if (field_indices contains key)
        fieldvals(field_indices(key))
      else
        get_fixed_field(key)
    }

    def get_field_if(fieldvals: IndexedSeq[String], key: String) = {
      check_values_fit_schema(fieldvals)
      if (field_indices contains key)
        Some(fieldvals(field_indices(key)))
      else
        get_fixed_field_if(key)
    }

    def get_field_or_else(fieldvals: IndexedSeq[String], key: String,
        default: String) = {
      check_values_fit_schema(fieldvals)
      if (field_indices contains key)
        fieldvals(field_indices(key))
      else
        get_fixed_field_or_else(key, default)
    }

    def get_fixed_field(key: String) = {
      if (fixed_values contains key)
        fixed_values(key)
      else
        throw new NoSuchElementException("key not found: %s" format key)
    }

    def get_fixed_field_if(key: String) = {
      if (fixed_values contains key)
        Some(fixed_values(key))
      else
        None
    }

    def get_fixed_field_or_else(key: String, default: String) = {
      if (fixed_values contains key)
        fixed_values(key)
      else
        default
    }

    /**
     * Convert a list of items into a row to be output directly to a text file.
     * (This does not include a trailing newline character.)
     */
    def make_row(fieldvals: Iterable[String]) = {
      check_values_fit_schema(fieldvals)
      fieldvals mkString split_text
    }

    /**
     * Output the schema to a file.
     */
    def output_schema_file(filehand: FileHandler, schema_file: String) {
      val schema_outstream = filehand.openw(schema_file)
      schema_outstream.println(make_row(fieldnames))
      for ((field, value) <- fixed_values)
        schema_outstream.println(Seq(field, value) mkString split_text)
      schema_outstream.close()
    }

    /**
     * Output the schema to a file.  The file will be named
     * `DIR/PREFIX-SUFFIX-schema.txt`.
     *
     * @return Name of constructed schema file.
     */
    def output_constructed_schema_file(filehand: FileHandler, dir: String,
        prefix: String, suffix: String) = {
      val schema_file = Schema.construct_schema_file(filehand, dir, prefix,
        suffix)
      output_schema_file(filehand, schema_file)
      schema_file
    }
  }

  class SchemaFromFile(
    val filehand: FileHandler,
    val filename: String,
    fieldnames: Iterable[String],
    fixed_values: Map[String, String] = Map[String, String](),
    split_text: String = "\t"
  ) extends Schema(fieldnames, fixed_values, split_text) { }

  /**
   * A Schema that can be used to select some fields from a larger schema.
   *
   * @param fieldnames Names of fields in this schema; should be a subset of
   *   the field names in `orig_schema`
   * @param fixed_values Fixed values in this schema
   * @param orig_schema Original schema from which fields have been selected.
   */
  class SubSchema(
    fieldnames: Iterable[String],
    fixed_values: Map[String, String] = Map[String, String](),
    val orig_schema: Schema
  ) extends Schema(fieldnames, fixed_values) {
    val orig_field_indices = {
      val names_set = fieldnames.toSet
      orig_schema.field_indices.filterKeys(names_set contains _).values.toSet
    }

    /**
     * Given a set of field values corresponding to the original schema
     * (`orig_schema`), produce a list of field values corresponding to this
     * schema.
     */
    def map_original_fieldvals(fieldvals: IndexedSeq[String]) =
      fieldvals.zipWithIndex.
        filter { case (x, ind) => orig_field_indices contains ind }.
        map { case (x, ind) => x }
  }

  object Schema {
    /**
     * Construct the name of a schema file, based on the given file handler,
     * directory, prefix and suffix.  The file will end with "-schema.txt".
     */
    def construct_schema_file(filehand: FileHandler, dir: String,
        prefix: String, suffix: String) =
      TextDBProcessor.construct_output_file(filehand, dir, prefix,
        suffix, "-schema.txt")

    /**
     * Locate the prefix in a schema after the directory and suffix have
     * been removed.
     */
    def get_schema_prefix(filehand: FileHandler, schema_file: String,
        suffix: String) = {
      val (_, base) = filehand.split_filename(schema_file)
      base.stripSuffix("-" + suffix + "-schema.txt")
    }

    /**
     * Read the given schema file.
     *
     * @param filehand File handler of schema file name.
     * @param schema_file Name of the schema file.
     * @param split_text Text used to split the fields of the schema and data
     *   files, usually TAB.
     */
    def read_schema_file(filehand: FileHandler, schema_file: String,
        split_text: String = "\t") = {
      val split_re = "\\Q" + split_text + "\\E"
      val lines = filehand.openr(schema_file)
      val fieldname_line = lines.next()
      val fieldnames = fieldname_line.split(split_re, -1)
      for (field <- fieldnames if field.length == 0)
        throw new FileFormatException(
          "Blank field name in schema file %s: fields are %s".
          format(schema_file, fieldnames))
      var fixed_fields = Map[String,String]()
      for (line <- lines) {
        val fixed = line.split(split_re, -1)
        if (fixed.length != 2)
          throw new FileFormatException(
            "For fixed fields (i.e. lines other than first) in schema file %s, should have two values (FIELD and VALUE), instead of %s".
            format(schema_file, line))
        val Array(from, to) = fixed
        if (from.length == 0)
          throw new FileFormatException(
            "Blank field name in fixed-value part of schema file %s: line is %s".
              format(schema_file, line))
        fixed_fields += (from -> to)
      }
      new SchemaFromFile(filehand, schema_file, fieldnames, fixed_fields,
        split_text)
    }

    /**
     * Convert a set of field names and values to a map, to make it easier
     * to work with them.  The result is a mutable order-preserving map,
     * which is important so that when converted back to separate lists of
     * names and values, the values are still written out correctly.
     * (The immutable order-preserving ListMap isn't sufficient since changing
     * a field value results in the field getting moved to the end.)
     *
     */
    def to_map(fieldnames: Iterable[String], fieldvals: IndexedSeq[String]) =
      mutable.LinkedHashMap[String, String]() ++ (fieldnames zip fieldvals)

    /**
     * Convert from a map back to a tuple of lists of field names and values.
     */
    def from_map(map: scala.collection.Map[String, String]) =
      map.toSeq.unzip

  }

  object TextDBProcessor {
    val possible_compression_re = """(\.bz2|\.bzip2|\.gz|\.gzip)?$"""
    val possible_compression_endings = Seq(".bz2", ".bzip2", ".gz", ".gzip")
    /**
     * For a given suffix, create a regular expression
     * ([[scala.util.matching.Regex]]) that matches document files of the
     * suffix.
     */
    def make_document_file_suffix_regex(suffix: String) = {
      val re_quoted_suffix = """-%s\.txt""" format suffix
      (re_quoted_suffix + possible_compression_re).r
    }
    /**
     * For a given suffix, create a regular expression
     * ([[scala.util.matching.Regex]]) that matches schema files of the
     * suffix.
     */
    def make_schema_file_suffix_regex(suffix: String) = {
      val re_quoted_suffix = """-%s-schema\.txt""" format suffix
      (re_quoted_suffix + possible_compression_re).r
    }

    /**
     * Construct the name of a file (either schema or document file), based
     * on the given file handler, directory, prefix, suffix and file ending.
     * For example, if the file ending is "-schema.txt", the file will be
     * named `DIR/PREFIX-SUFFIX-schema.txt`.
     */
    def construct_output_file(filehand: FileHandler, dir: String,
        prefix: String, suffix: String, file_ending: String) = {
      val new_base = prefix + "-" + suffix + file_ending
      filehand.join_filename(dir, new_base)
    }

    def get_document_prefix(filehand: FileHandler, file: String,
        suffix: String): String = {
      val (_, base) = filehand.split_filename(file)
      for (ending <- possible_compression_endings) {
        val compressed_ending = ".txt" + ending
        if (base.endsWith(compressed_ending))
          return base.stripSuffix("-" + suffix + compressed_ending)
      }
      base.stripSuffix("-" + suffix + ".txt")
    }

    /**
     * Locate the schema file of the appropriate suffix in the given directory.
     */
    def find_schema_file(filehand: FileHandler, dir: String, suffix: String) = {
      val schema_regex = make_schema_file_suffix_regex(suffix)
      val all_files = filehand.list_files(dir)
      val files =
        (for (file <- all_files
          if schema_regex.findFirstMatchIn(file) != None) yield file).toSeq
      if (files.length == 0)
        throw new FileFormatException(
          "Found no schema files (matching %s) in directory %s"
          format (schema_regex, dir))
      if (files.length > 1)
        throw new FileFormatException(
          "Found multiple schema files (matching %s) in directory %s: %s"
          format (schema_regex, dir, files))
      files(0)
    }

    /**
     * Locate and read the schema file of the appropriate suffix in the
     * given directory.
     */
    def read_schema_from_textdb(filehand: FileHandler, dir: String,
          suffix: String) = {
      val schema_file = find_schema_file(filehand, dir, suffix)
      Schema.read_schema_file(filehand, schema_file)
    }

    /**
     * List only the document files of the appropriate suffix.
     */
    def filter_file_by_suffix(file: String, suffix: String) = {
      val filter = make_document_file_suffix_regex(suffix)
      filter.findFirstMatchIn(file) != None
    }

    /**
     * Read a textdb corpus from a directory and return the schema and an
     * iterator over all data files.  This will recursively process any
     * subdirectories looking for data files.  The data files must have a suffix
     * in their names that matches the given suffix. (If you want more control
     * over the processing, call `read_schema_from_textdb`,
     * `iter_files_recursively`, and `filter_file_by_suffix`.)
     *
     * @param filehand File handler object of the directory
     * @param dir Directory to read
     * @param suffix Suffix picking out the correct data files
     * @param with_message If true, "Processing ..." messages will be
     *   displayed as each file is processed and as each directory is visited
     *   during processing.
     *
     * @return A tuple `(schema, files)` where `schema` is the schema for the
     *   corpus and `files` is an iterator over data files.
     */
    def get_textdb_files(filehand: FileHandler, dir: String,
        suffix: String, with_messages: Boolean = true) = {
      val schema = read_schema_from_textdb(filehand, dir, suffix)
      val files = iter_files_recursively(filehand, Iterable(dir)).
          filter(filter_file_by_suffix(_, suffix))
      val files_with_message =
        if (with_messages)
          iter_files_with_message(filehand, files)
        else
          files
      (schema, files_with_message)
    }

    /**
     * Read a corpus from a directory and return the result of processing the
     * rows in the corpus. (If you want more control over the processing,
     * call `read_schema_from_textdb` and use `NewTextDBProcessor`.)
     *
     * @param filehand File handler object of the directory
     * @param dir Directory to read
     * @param suffix Suffix picking out the correct data files
     * @param with_message If true, "Processing ..." messages will be
     *   displayed as each file is processed and as each directory is visited
     *   during processing.
     *
     * @return An iterator of iterators of values.  There is one inner iterator
     *   per file read in, and each such iterator contains all the values
     *   read from the file. (There may be fewer values than rows in a file
     *   if some rows were badly formatted.)
     */
    def read_textdb(filehand: FileHandler, dir: String,
        suffix: String, with_messages: Boolean = true) = {
      val (schema, fields) =
        read_textdb_with_schema(filehand, dir, suffix, with_messages)
      fields
    }

    /**
     * Read the items from a given textdb file.  Returns an iterator
     * over a list of field values.
     */
    def read_textdb_file(filehand: FileHandler, file: String,
        schema: Schema) = {
      filehand.openr(file).zipWithIndex.flatMap {
        case (line, idx) => line_to_fields(line, idx + 1, schema)
      }
    }

    /**
     * Same as `read_textdb` but return also return the schema.
     *
     * @return A tuple `(schema, field_iter)` where `field_iter` is an
     *   iterator of iterators of fields.
     */
    def read_textdb_with_schema(filehand: FileHandler, dir: String,
        suffix: String, with_messages: Boolean = true) = {
      val (schema, files) =
        get_textdb_files(filehand, dir, suffix, with_messages)
      val fields = files.map(read_textdb_file(filehand, _, schema))
      (schema, fields)
    }

    /*
    FIXME: Should be implemented.

    def read_textdb_with_filenames(filehand: FileHandler, dir: String) = ...
    */

    /**
     * Return a list of shell-style wildcard patterns matching all the document
     * files in the given directory with the given suffix (including compressed
     * files).
     */
    def get_matching_patterns(filehand: FileHandler, dir: String,
        suffix: String) = {
      val possible_endings = Seq("") ++ possible_compression_endings
      for {ending <- possible_endings
           full_ending = "-%s.txt%s" format (suffix, ending)
           pattern = filehand.join_filename(dir, "*%s" format full_ending)
           all_files = filehand.list_files(dir)
           files = all_files.filter(_ endsWith full_ending)
           if files.size > 0}
        yield pattern
    }
  }

  /**
   * Parse a line into fields, according to `split_text` (usually TAB).
   * `lineno` and `schema` are used for verifying the correct number of
   * fields and handling errors.
   */
  def line_to_fields(line: String, lineno: Long, schema: Schema
      ): Option[IndexedSeq[String]] = {
    val fieldvals = line.split(schema.split_re, -1).toIndexedSeq
    if (fieldvals.size != schema.fieldnames.size) {
      warning(
        """Line %s: Bad record, expected %s fields, saw %s fields;
        skipping line=%s""", lineno, schema.fieldnames.size,
        fieldvals.size, line)
      None
    } else
      Some(fieldvals)
  }

  /**
   * Class for writing a textdb database.
   *
   * @param schema the schema describing the fields in the document file
   * @param suffix the suffix of the data files, as described in the
   *   `textdb` package
   */
  class TextDBWriter(
    val schema: Schema,
    val suffix: String
  ) {
    /**
     * Open a document file and return an output stream.  The file will be
     * named `DIR/PREFIX-SUFFIX.txt`, possibly with an additional suffix
     * (e.g. `.bz2`), depending on the specified compression (which defaults
     * to no compression).  Call `output_row` to output a row describing
     * a document.
     */
    def open_document_file(filehand: FileHandler, dir: String,
        prefix: String, compression: String = "none") = {
      val file = TextDBProcessor.construct_output_file(filehand, dir,
        prefix, suffix, ".txt")
      filehand.openw(file, compression = compression)
    }

    /**
     * Output the schema to a file.  The file will be named
     * `DIR/PREFIX-SUFFIX-schema.txt`.
     *
     * @return Name of schema file.
     */
    def output_schema_file(filehand: FileHandler, dir: String,
        prefix: String) =
      schema.output_constructed_schema_file(filehand, dir, prefix, suffix)
  }

  val document_metadata_suffix = "document-metadata"
  val unigram_counts_suffix = "unigram-counts"
  val ngram_counts_suffix = "ngram-counts"
  val text_suffix = "text"

  class EncodeDecode(val chars_to_encode: Iterable[Char]) {
    private val encode_chars_regex = "[%s]".format(chars_to_encode mkString "").r
    private val encode_chars_map =
      chars_to_encode.map(c => (c.toString, "%%%02X".format(c.toInt))).toMap
    private val decode_chars_map =
      encode_chars_map.toSeq.flatMap {
        case (dec, enc) => Seq((enc, dec), (enc.toLowerCase, dec)) }.toMap
    private val decode_chars_regex =
      "(%s)".format(decode_chars_map.keys mkString "|").r

    def encode(str: String) =
      encode_chars_regex.replaceAllIn(str, m => encode_chars_map(m.matched))
    def decode(str: String) =
      decode_chars_regex.replaceAllIn(str, m => decode_chars_map(m.matched))
  }

  private val endec_string_for_count_map_field =
    new EncodeDecode(Seq('%', ':', ' ', '\t', '\n', '\r', '\f'))
  private val endec_string_for_sequence_field =
    new EncodeDecode(Seq('%', '>', '\t', '\n', '\r', '\f'))
  private val endec_string_for_whole_field =
    new EncodeDecode(Seq('%', '\t', '\n', '\r', '\f'))

  /**
   * Encode a word for placement inside a "counts" field.  Colons and spaces
   * are used for separation inside of a field, and tabs and newlines are used
   * for separating fields and records.  We need to escape all of these
   * characters (normally whitespace should be filtered out during
   * tokenization, but for some applications it won't necessarily).  We do this
   * using URL-style-encoding, e.g. replacing : by %3A; hence we also have to
   * escape % signs. (We could equally well use HTML-style encoding; then we'd
   * have to escape &amp; instead of :.) Note that regardless of whether we use
   * URL-style or HTML-style encoding, we probably want to do the encoding
   * ourselves rather than use a predefined encoder.  We could in fact use the
   * presupplied URL encoder, but it would encode all sorts of stuff, which is
   * unnecessary and would make the raw files harder to read.  In the case of
   * HTML-style encoding, : isn't even escaped, so that wouldn't work at all.
   */
  def encode_string_for_count_map_field(word: String) =
    endec_string_for_count_map_field.encode(word)

  /**
   * Encode an n-gram into text suitable for the "counts" field.
   The
   * individual words are separated by colons, and each word is encoded
   * using `encode_string_for_count_map_field`.  We need to encode '\n'
   * (record separator), '\t' (field separator), ' ' (separator between
   * word/count pairs), ':' (separator between word and count),
   * '%' (encoding indicator).
   */
  def encode_ngram_for_count_map_field(ngram: Iterable[String]) = {
    ngram.map(encode_string_for_count_map_field) mkString ":"
  }

  /**
   * Decode a word encoded using `encode_string_for_count_map_field`.
   */
  def decode_string_for_count_map_field(word: String) =
    endec_string_for_count_map_field.decode(word)

  /**
   * Encode a string for placement in a field consisting of a sequence
   * of strings.  This is similar to `encode_string_for_count_map_field` except
   * that we don't encode spaces.  We encode '&gt;' for use as a separator
   * inside of a field (since it's almost certain not to occur, because
   * we generally get HTML-encoded text; and even if not, it's fairly
   * rare).
   */
  def encode_string_for_sequence_field(word: String) =
    endec_string_for_sequence_field.encode(word)

  /**
   * Decode a string encoded using `encode_string_for_sequence_field`.
   */
  def decode_string_for_sequence_field(word: String) =
    endec_string_for_sequence_field.decode(word)

  /**
   * Encode a string for placement in a field by itself.  This is similar
   * to `encode_word_for_sequence_field` except that we don't encode the &gt;
   * sign.
   */
  def encode_string_for_whole_field(word: String) =
    endec_string_for_whole_field.encode(word)

  /**
   * Decode a string encoded using `encode_string_for_whole_field`.
   */
  def decode_string_for_whole_field(word: String) =
    endec_string_for_whole_field.decode(word)

  /**
   * Decode an n-gram encoded using `encode_ngram_for_count_map_field`.
   */
  def decode_ngram_for_count_map_field(ngram: String) = {
    ngram.split(":", -1).map(decode_string_for_count_map_field)
  }

  /**
   * Split counts field into the encoded n-gram section and the word count.
   */
  def shallow_split_count_map_field(field: String) = {
    val last_colon = field.lastIndexOf(':')
    if (last_colon < 0)
      throw FileFormatException(
        "Counts field must be of the form WORD:WORD:...:COUNT, but %s seen"
          format field)
    val count = field.slice(last_colon + 1, field.length).toInt
    (field.slice(0, last_colon), count)
  }

  /**
   * Split counts field into n-gram and word count.
   */
  def deep_split_count_map_field(field: String) = {
    val (encoded_ngram, count) = shallow_split_count_map_field(field)
    (decode_ngram_for_count_map_field(encoded_ngram), count)
  }

  /**
   * Serialize a sequence of (encoded-word, count) pairs into the format used
   * in a corpus.  The word or ngram must already have been encoded using
   * `encode_string_for_count_map_field` or `encode_ngram_for_count_map_field`.
   */
  def shallow_encode_count_map(seq: Iterable[(String, Int)]) = {
    // Sorting isn't strictly necessary but ensures consistent output as well
    // as putting the most significant items first, for visual confirmation.
    (for ((word, count) <- seq.toSeq sortWith (_._2 > _._2)) yield
      ("%s:%s" format (word, count))) mkString " "
  }

  /**
   * Serialize a sequence of (word, count) pairs into the format used
   * in a corpus.
   */
  def encode_count_map(seq: Iterable[(String, Int)]) = {
    shallow_encode_count_map(seq map {
      case (word, count) => (encode_string_for_count_map_field(word), count)
    })
  }

  /**
   * Deserialize an encoded word-count map into a sequence of
   * (word, count) pairs.
   */
  def decode_count_map(encoded: String) = {
    if (encoded.length == 0)
      Array[(String, Int)]()
    else
      {
      val wordcounts = encoded.split(" ")
      for (wordcount <- wordcounts) yield {
        val split_wordcount = wordcount.split(":", -1)
        if (split_wordcount.length != 2)
          throw FileFormatException(
            "For unigram counts, items must be of the form WORD:COUNT, but %s seen"
            format wordcount)
        val Array(word, strcount) = split_wordcount
        if (word.length == 0)
          throw FileFormatException(
            "For unigram counts, WORD in WORD:COUNT must not be empty, but %s seen"
            format wordcount)
        val count = strcount.toInt
        val decoded_word = decode_string_for_count_map_field(word)
        (decoded_word, count)
      }
    }
  }

  object Encoder {
    def count_map(x: scala.collection.Map[String, Int]) =
      encode_count_map(x.toSeq)
    def count_map_seq(x: Iterable[(String, Int)]) =
      encode_count_map(x)
    def string(x: String) = encode_string_for_whole_field(x)
    def string_in_seq(x: String) = encode_string_for_sequence_field(x)
    def seq_string(x: Iterable[String]) =
      x.map(encode_string_for_sequence_field) mkString ">>"
    def timestamp(x: Long) = x.toString
    def long(x: Long) = x.toString
    def int(x: Int) = x.toString
    def double(x: Double) = x.toString
  }

  object Decoder {
    def count_map(x: String) = decode_count_map(x).toMap
    def count_map_seq(x: String) = decode_count_map(x)
    def string(x: String) = decode_string_for_whole_field(x)
    def seq_string(x: String) =
      x.split(">>", -1).map(decode_string_for_sequence_field)
    def timestamp(x: String) = x.toLong
    def long(x: String) = x.toLong
    def int(x: String) = x.toInt
    def double(x: String) = x.toDouble
  }

}
