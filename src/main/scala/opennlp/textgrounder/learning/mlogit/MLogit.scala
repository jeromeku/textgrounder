///////////////////////////////////////////////////////////////////////////////
//  MLogit.scala
//
//  Copyright (C) 2013 Ben Wing, The University of Texas at Austin
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
package learning.mlogit

import learning._
import util.debug._
import util.io.localfh
import util.print.{errprint,internal_error}

import org.ddahl.jvmr.RInScala

import scala.collection.mutable
import scala.reflect.ClassTag

/**
 * A conditional logit (a type of multinomial logit, which is a type of
 * GLM or generalized linear model) for solving a reranking problem.
 * This implements the equivalent of a single-weight multi-label classifier.
 *
 * @author Ben Wing
 *
 * Note that for a binary classification model, we can write logistic
 * regression as (see Wikipedia "logistic regression"):
 *
 * logit(p(y_i | X_i)) = β · x_i  for a = 1 ... N
 *
 * for the i'th training instance, with corresponding feature vector x_i,
 * weights β and binary label y_i.
 *
 * If we have K different choices, a classifier is normally written
 *
 * ln p(y_i = 1) = β_1 · x_i - ln Z
 * ln p(y_i = 2) = β_2 · x_i - ln Z
 * ...
 * ln p(y_i = K) = β_k · x_i - ln Z
 *
 * for a multinomial label y_i, with a set of weights β_k for k = 1 ... K,
 * where each choice has its own weight vector, and a normalizing function Z
 * that is required so that the probabilities all sum to 1:
 *
 * \sum_{k=1}^{K} p(y_i = k) = 1
 *
 * This is a standard multinomial logit model.
 *
 * In vector form:
 *
 * ln p([y_i = k]) = B x_i - [ln Z]
 *
 * where [y_i = k] is a vector of booleans where exactly one is true; B is
 * a matrix of of β_1,β_2,...,β_k; and [ln Z] is a vector containing the
 * same value ln Z duplicated K times.
 *
 * But in the case of a reranker, we have a set of distinct feature
 * vectors for each candidate, i.e. we have a separate set of covariates for
 * each choice. The choices are all equivalent to each other and so it makes
 * no sense to have choice-specific weights. Thus:
 *
 * ln p(y_i = 1) = β · x_{i1} - ln Z
 * ln p(y_i = 2) = β · x_{i2} - ln Z
 * ...
 * ln p(y_i = K) = β · x_{iK} - ln Z
 *
 * In this case, the distinct y_i's are simply indices noting the distinct
 * candidates, and there are choice-specific covariates x_{iK}, which can be
 * grouped into a matrix X_i. Note that for the entire set of N training
 * instances, there will be N separate matrices of covariates. These matrices
 * are often stacked together into one big matrix which each row listing
 * the covariates for a given individual (aka data instance) and choice
 * (aka candidate).
 *
 * This is a standard conditional logit model.

 * In vector form:
 *
 * ln p([y_i = k]) = X_i β - [ln Z]
 *
 * We use the 'mlogit' package in R, which is specifically designed to solve
 * models of this sort, and can do fast BFGS optimization.
 */

/**
 * Class for training a multi-label perceptron with only a single set of
 * weights for all labels.
 */
trait ConditionalLogitTrainer[DI <: DataInstance]
    extends SingleWeightMultiLabelLinearClassifierTrainer[DI] {
}

/**
 * Train a single-weight multi-label perceptron without cost-sensitivity,
 * using the basic algorithm.  In this case, if we predict a correct label,
 * we don't change the weights; otherwise, we simply use a specified scale
 * factor.
 */
class RConditionalLogitTrainer[DI <: DataInstance](
  val vector_factory: SimpleVectorFactory
) extends ConditionalLogitTrainer[DI] {

  /**
   * Undo the conversion in `import_labeled_instances` to get the long-format
   * 2-d matrix used in R's mlogit() function. The return value is:
   *
   * (header:Array[String], data:Array[Array[String]])
   *
   * i.e. a header line followed by a 2-d array of strings, all ready to
   * be directly output to a file with spaces in between columns.
   */
  def training_data_to_file(headers: Iterable[String],
      rows: Iterable[((Int, String, Boolean), Iterable[Double])]) = {
    val rheaders = Array("indiv", "label", "choice") ++ headers
    val sep = " "
    val filename =
      java.io.File.createTempFile("textgrounder.mlogit", null).toString
    val file = localfh.openw(filename)
    file.println(rheaders mkString sep)
    rows.foreach { case ((indiv, labelstr, choice), datarow) =>
      assert(headers.size == datarow.size)
      val indivstr = indiv.toString
      val choicestr = if (choice) "TRUE" else "FALSE"
      val datastr = datarow.map(_.toString).toArray
      val line = (Array(indivstr, "\"" + labelstr + "\"", choicestr) ++
        datastr) mkString sep
      file.println(line)
    }
    file.close()
    filename
  }

  /**
   * Convert the set of instances into a long-style data frame in R with
   * the name `framename`, for use with the `mlogit` function.
   */
  def do_mlogit(training_data: TrainingData[DI]) = {
    val R = RInScala()

    val removed_features = training_data.removed_features
    val frame = "frame" // Name of variable to use for data, etc.
    val (headers, rows) =
      AggregateFeatureVector.export_training_data(training_data)
    val rheaders = headers.map {
      _.replaceAll("[^A-Za-z0-9_]", ".")
    }
    // errprint("#1")
    R.eval("require(mlogit)")

    val filename = training_data_to_file(rheaders, rows)
    errprint("Filename: %s", filename)
    R.eval(s"""$frame = read.table("$filename", header=TRUE)""")
    // errprint("#10")
    R.eval(s"""$frame = mlogit.data(choice="choice", shape="long", alt.var="label", chid.var="indiv", $frame)""")
    // errprint("#11")
    R.eval(s"""m.$frame = mlogit(choice ~ ${rheaders mkString " + "} | -1, $frame)""")
    // errprint("#12")
    val weights = R.toVector[Double](s"as.vector(m.$frame$$coefficients)")
    assert(weights.size == headers.size,
      "Weights size %s should = headers size %s" format (weights.size,
        headers.size))
    // Retrieve total number of features = proper size of weight vector
    val head = training_data.data.head._1.feature_vector
    val F = head.feature_mapper.number_of_indices
    assert(weights.size + removed_features.size == F,
      "Weights size %s + #removed-features %s should = #features %s" format (
        weights.size, removed_features.size, F))
    // Expand the weights by inserting the removed features in the right
    // places, with weight 0.
    val expanded_buffer = mutable.Buffer.fill(F)(0.0)
    val nonsingular_indices =
      (collection.SortedSet[FeatIndex]() ++ (0 until F)) diff removed_features
    for ((weight, index) <- (weights zip nonsingular_indices))
      expanded_buffer(index) = weight
    expanded_buffer.toArray
  }

  def get_weights(training_data: TrainingData[DI]): (VectorAggregate, Int) = {
    val rweights = do_mlogit(training_data)
    if (debug("weights"))
      errprint("Weights: %s", rweights)
    val vecagg = SingleVectorAggregate(ArrayVector(rweights))
    (vecagg, 1)
  }
}

