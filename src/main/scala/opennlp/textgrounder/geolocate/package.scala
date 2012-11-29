package opennlp.textgrounder

import gridlocate._
import util.distances._

package object geolocate {
  /**
   * A general trait holding SphereDoc-specific code for storing the
   * result of evaluation on a document.  Here we simply compute the
   * true and predicted "degree distances" -- i.e. measured in degrees,
   * rather than in actual distance along a great circle.
   */
  class SphereDocEvalResult(
    stats: DocEvalResult[SphereCoord]
  ) {
    /**
     * Distance in degrees between document's coordinate and central
     * point of true cell
     */
    val true_degdist = degree_dist(stats.document.coord, stats.true_center)
    /**
     * Distance in degrees between doc's coordinate and predicted
     * coordinate
     */
    val pred_degdist = degree_dist(stats.document.coord, stats.pred_coord)
  }

  implicit def to_SphereDocEvalResult(
    stats: DocEvalResult[SphereCoord]
  ) = new SphereDocEvalResult(stats)

  type SphereDoc = GeoDoc[SphereCoord]
  type SphereCell = GeoCell[SphereCoord]
  type SphereGrid = GeoGrid[SphereCoord]
  def get_sphere_docfact(grid: SphereGrid) =
    grid.docfact.asInstanceOf[SphereDocFactory]
}
