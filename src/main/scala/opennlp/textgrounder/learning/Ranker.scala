package opennlp.textgrounder
package learning

import worddist.WordDist._
import util.metering._
import util.print._
import learning._

import gridlocate.GridLocateDriver.Debug._

/**
 * A basic ranker.  Given a query item, return a list of ranked answers from
 * best to worst, with a score for each.  The score must not increase from
 * any answer to the next one.
 */
trait Ranker[Query, Answer] {
  /**
   * Evaluate a query item, returning a list of ranked answers from best to
   * worst, with a score for each.  The score must not increase from any
   * answer to the next one.  Any answers mentioned in `include` must be
   * included in the returned list.
   */
  def evaluate(item: Query, include: Iterable[Answer]):
    Iterable[(Answer, Double)]
}

/**
 * Common methods and fields between `Reranker` and reranker trainers.
 */
trait RerankerLike[Query, Answer] {
  /**
   * Number of top-ranked items to submit to reranking.
   */
  val top_n: Int
}

/**
 * A reranker.  This is a particular type of ranker that involves two
 * steps: One to compute an initial ranking, and a second to do a more
 * accurate reranking of some subset of the highest-ranked answers.  The
 * idea is that a more accurate value can be computed when there are fewer
 * possible answers to distinguish -- assuming that the initial ranker
 * is able to include the correct answer near the top significantly more
 * often than actually at the top.
 */
trait Reranker[Query, Answer] extends Ranker[Query, Answer] with RerankerLike[Query, Answer] {
  /** Ranker for generating initial ranking. */
  protected def initial_ranker: Ranker[Query, Answer]

  /**
   * Rerank the given answers, based on an initial ranking.
   */
  protected def rerank_answers(item: Query,
    initial_ranking: Iterable[(Answer, Double)]): Iterable[(Answer, Double)]

  def evaluate_with_initial_ranking(item: Query,
      include: Iterable[Answer]) = {
    val initial_ranking = initial_ranker.evaluate(item, include)
    val (to_rerank, others) = initial_ranking.splitAt(top_n)
    val reranking = rerank_answers(item, to_rerank) ++ others
    (initial_ranking, reranking)
  }

  override def evaluate(item: Query, include: Iterable[Answer]) = {
    val (initial_ranking, reranking) =
      evaluate_with_initial_ranking(item, include)
    reranking
  }
}

/**
 * A pointwise reranker that uses a scoring classifier to assign a score
 * to each possible answer to be reranked.  The idea is that, for each
 * possible answer, we create test instances based on a combination of the
 * query item and answer and score the instances to determine the ranking.
 *
 * @tparam Query type of a query
 * @tparam Answer type of a possible answer
 * @tparam RerankInst type of the rerank instance encapsulating a query-answer pair
 *   and fed to the rerank classifier
 */
trait PointwiseClassifyingReranker[Query, Answer, RerankInst]
    extends Reranker[Query, Answer] {
  /** Scoring classifier for use in reranking. */
  protected def rerank_classifier: ScoringBinaryClassifier[RerankInst]

  /**
   * Create a rerank instance to feed to the classifier during evaluation,
   * given a query item, a potential answer from the ranker, and the score
   * from the initial ranker on this answer.
   */
  protected def create_rerank_evaluation_instance(query: Query, answer: Answer,
    initial_score: Double): RerankInst

  protected def rerank_answers(item: Query,
      answers: Iterable[(Answer, Double)]) = {
    val new_scores =
      for {(answer, score) <- answers
           instance = create_rerank_evaluation_instance(item, answer, score)
           new_score = rerank_classifier.score_item(instance)
          }
        yield (answer, new_score)
    new_scores.toIndexedSeq sortWith (_._2 > _._2)
  }
}

/**
 * A class for training a pointwise classifying reranker.
 *
 * There are various types of training data:
 * -- External training data is the data supplied externally (e.g. from a
 *    corpus), consisting of ExtInst items.
 * -- Initial-ranker training data is the data used to train an initial ranker,
 *    which supplies the base ranking upon which the reranker builds.
 *    This also consists of ExtInst items and is taken directly from
 *    the external training data or a subset.
 * -- Reranker training data is the data used to train a rerank classifier,
 *    i.e. the classifier used to compute the scores that underlie the reranking.
 *    This consists of (RerankInst, Boolean) pairs, i.e. pairs of rerank
 *    instances (computed from a query-answer pair) and booleans indicating
 *    whether the instance corresponds to a true answer.
 *
 * Generally, a data instance of type `ExtInst` in the external training
 * data will describe an object of type `Query`, along with the correct
 * answer. However, it need not merely be a pair of `Query` and `Answer`. In
 * particular, the `ExtInst` data may be the raw-data form of an object that
 * can only be created with respect to some particular training corpus (e.g.
 * for doing back-off when computing word distributions).  Hence, a method
 * is provided to convert from one to the other, given a trained initial
 * ranker against which the "cooked" query object will be looked up. For
 * example, in the case of GridLocate, `ExtInst` is of type
 * `DocStatus[RawDocument]`, which directly describes the data read from a
 * corpus, while `Query` is of type `GeoDoc[Co]`, which contains (among other
 * things) a word distribution with statistics computed using back-off, just
 * as described above.
 *
 * Training is as follows:
 *
 * 1. External training data is supplied by the caller.
 *
 * 2. Split this data into N parts (`number_of_splits`).  Process each part
 *    in turn.  For a given part, its data will be used to generate rerank
 *    training data, using an initial ranker trained on the remaining parts.
 *
 * 3. From each data item in the external training data, a series of rerank
 *    training instances are generated as follows:
 *
 *    (1) rank the data item using the initial ranker to produce a set of
 *        possible answers;
 *    (2) if necessary, augment the possible answers to include the correct
 *        one;
 *    (3) create a rerank training instance for each combination of query item
 *        and answer, with "correct" or "incorrect" indicated.
 *
 * @tparam Query type of a query
 * @tparam Answer type of a possible answer
 * @tparam RerankInst type of the rerank instance encapsulating a query-answer pair
 * @tparam ExtInst type of the instances used in external training data
 */
trait PointwiseClassifyingRerankerTrainer[Query, Answer, RerankInst, ExtInst]
extends RerankerLike[Query, Answer] { self =>
  /**
   * Number of splits used in the training data, to create the reranker.
   */
  val number_of_splits: Int

  /**
   * Create the classifier used for reranking, given a set of rerank training
   * data.
   */
  protected def create_rerank_classifier(
    data: Iterable[(RerankInst, Boolean)]
  ): ScoringBinaryClassifier[RerankInst]

  /**
   * Create a rerank training instance to train the classifier, given a query
   * item, a potential answer from the ranker, and the score from the initial
   * ranker on this answer.
   */
  protected def create_rerank_training_instance(query: Query, answer: Answer,
    initial_score: Double): RerankInst

  /**
   * Create a rerank instance to feed to the classifier during evaluation,
   * given a query item, a potential answer from the ranker, and the score
   * from the initial ranker on this answer.  Note that this function may need
   * to work differently from the corresponding function used during training
   * (e.g. in the handling of previously unseen words).
   */
  protected def create_rerank_evaluation_instance(query: Query, answer: Answer,
    initial_score: Double): RerankInst

  /**
   * Create an initial ranker based on initial-ranker training data.
   */
  protected def create_initial_ranker(data: Iterable[ExtInst]):
    Ranker[Query, Answer]

  /**
   * Convert an external instance into a query-answer pair, if possible,
   * given the external instance and the initial ranker trained from other
   * external instances.
   */
  protected def external_instances_to_query_answer_pairs(
    inst: Iterator[ExtInst], initial_ranker: Ranker[Query, Answer]
  ): Iterator[(Query, Answer)]

  /**
   * Display a query item (typically for debugging purposes).
   */
  def display_query_item(item: Query) = item.toString

  /**
   * Display an answer (typically for debugging purposes).
   */
  def display_answer(answer: Answer) = answer.toString

  /**
   * Generate rerank training instances for a given instance from the
   * external training data.
   *
   * @param initial_ranker Initial ranker used to score the answer.
   */
  protected def get_rerank_training_instances(
    query: Query, true_answer: Answer, initial_ranker: Ranker[Query, Answer]
  ) = {
    val initial_answers =
      initial_ranker.evaluate(query, Iterable(true_answer))
    val top_answers = initial_answers.take(top_n)
    val answers =
      if (top_answers.find(_._1 == true_answer) != None)
        top_answers
      else
        top_answers ++
          Iterable(initial_answers.find(_._1 == true_answer).get)
    for {(possible_answer, score) <- answers
         is_correct = possible_answer == true_answer
        }
      yield (
        create_rerank_training_instance(query, possible_answer, score),
        is_correct
      )
  }

  /**
   * Given one of the splits of external training data and an initial ranker
   * created from the remainder, generate the corresponding rerank training
   * instances.
   */
  protected def get_rerank_training_data_for_split(
      splitnum: Int, data: Iterator[ExtInst],
      initial_ranker: Ranker[Query, Answer]) = {
    val query_answer_pairs =
      external_instances_to_query_answer_pairs(data, initial_ranker)
    val task = new Meter("generating",
      "split-#%d rerank training instance" format splitnum)
    if (debug("rerank-training")) {
      query_answer_pairs.zipWithIndex.flatMapMetered(task) {
        case ((query, answer), index) => {
          val prefix = "#%d: " format (index + 1)
          errprint("%sTraining item: %s", prefix, display_query_item(query))
          errprint("%sTrue answer: %s", prefix, display_answer(answer))
          val training_insts =
            get_rerank_training_instances(query, answer, initial_ranker)
          for (((featvec, correct), instind) <- training_insts.zipWithIndex) {
            val instpref = "%s#%d: " format (prefix, instind + 1)
            val correctstr =
              if (correct) "CORRECT" else "INCORRECT"
            errprint("%s%s: %s", instpref, correctstr, featvec)
          }
          training_insts
        }
      }
    } else {
      query_answer_pairs.flatMapMetered(task) {
        case (query, answer) =>
          get_rerank_training_instances(query, answer, initial_ranker)
      }
    }
  }

  /**
   * Given external training data, generate the corresponding rerank training
   * data.  This involves splitting up the rerank data into parts and training
   * separate initial rankers, as described above.
   */
  protected def get_rerank_training_data(training_data: Iterable[ExtInst]) = {
    val numitems = training_data.size
    errprint("Total number of training documents: %s.", numitems)
    // If number of docs is not an even multiple of number of splits,
    // round the split size up -- we want the last split a bit smaller
    // rather than an extra split with only a couple of items.
    val splitsize = (numitems + number_of_splits - 1) / number_of_splits
    errprint("Number of splits for training reranker: %s.", number_of_splits)
    errprint("Size of each split: %s documents.", splitsize)
    (0 until number_of_splits) flatMap { rerank_split_num =>
      errprint("Generating data for split %s" format rerank_split_num)
      val split_training_data = training_data.grouped(splitsize).zipWithIndex
      val (rerank_splits, initrank_splits) = split_training_data partition {
        case (data, num) => num == rerank_split_num
      }
      val rerank_data = rerank_splits.flatMap(_._1)
      val initrank_data = initrank_splits.flatMap(_._1).toIterable
      val split_initial_ranker = create_initial_ranker(initrank_data)
      get_rerank_training_data_for_split(rerank_split_num, rerank_data,
        split_initial_ranker)
    }
  }

  /**
   * Train a rerank classifier, based on external training data.
   */
  protected def train_rerank_classifier(
    training_data: Iterable[ExtInst]
  ) = {
    val rerank_training_data = get_rerank_training_data(training_data)
    create_rerank_classifier(rerank_training_data)
  }

  /**
   * Actually create a reranker object, given a rerank classifier and
   * initial ranker.
   */
  protected def create_reranker(
    _rerank_classifier: ScoringBinaryClassifier[RerankInst],
    _initial_ranker: Ranker[Query, Answer]
  ) = {
    new PointwiseClassifyingReranker[Query, Answer, RerankInst] {
      protected val rerank_classifier = _rerank_classifier
      protected val initial_ranker = _initial_ranker
      val top_n = self.top_n
      protected def create_rerank_evaluation_instance(query: Query,
          answer: Answer, initial_score: Double) = {
        self.create_rerank_evaluation_instance(query, answer, initial_score)
      }
    }
  }

  /**
   * Train a reranker, based on external training data.
   */
  def apply(training_data: Iterable[ExtInst]) = {
    val rerank_classifier = train_rerank_classifier(training_data)
    val initial_ranker = create_initial_ranker(training_data)
    create_reranker(rerank_classifier, initial_ranker)
  }
}


/**
 * A scoring binary classifier.  Given a query item, return a score, with
 * higher numbers indicating greater likelihood of being "positive".
 */
trait ScoringBinaryClassifier[Query] {
  /**
   * The value of `minimum_positive` indicates the dividing line between values
   * that should be considered positive and those that should be considered
   * negative; typically this will be 0 or 0.5. */
  def minimum_positive: Double
  def score_item(item: Query): Double
}

/**
 * An adapter class converting `BinaryLinearClassifier` (from the perceptron
 * package) into a `ScoringBinaryClassifier`.
 * FIXME: Just use one of the two everywhere.
 */
class LinearClassifierAdapter (
  cfier: BinaryLinearClassifier
) extends ScoringBinaryClassifier[FeatureVector] {
  /**
   * The value of `minimum_positive` indicates the dividing line between values
   * that should be considered positive and those that should be considered
   * negative; typically this will be 0 or 0.5. */
  def minimum_positive = 0.0
  def score_item(item: FeatureVector) = cfier.binary_score(item)
}

/**
 * A trivial scoring binary classifier that simply returns the already
 * existing score from a ranker.
 */
class TrivialScoringBinaryClassifier(
  val minimum_positive: Double
) extends ScoringBinaryClassifier[Double] {
  def score_item(item: Double) = {
    errprint("Trivial scoring item %s", item)
    item
  }
}