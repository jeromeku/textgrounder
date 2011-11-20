package opennlp.textgrounder.geolocate

import java.io._
import javax.xml.datatype._
import javax.xml.stream._
import opennlp.textgrounder.topo._
import opennlp.textgrounder.util.KMLUtil
import scala.collection.JavaConversions._
import org.clapper.argot._

object ErrorKMLGenerator {

  val DOC_PREFIX = "Document "
  val TRUE_COORD_PREFIX = ") at ("
  val PRED_COORD_PREFIX = " predicted cell center at ("
  

  val factory = XMLOutputFactory.newInstance

  def parseLogFile(filename: String): List[(String, Coordinate, Coordinate)] = {
    val lines = scala.io.Source.fromFile(filename).getLines

    var docName:String = null
    var trueCoord:Coordinate = null
    var predCoord:Coordinate = null

    (for(line <- lines) yield {
      if(line.startsWith("#")) {

        if(line.contains(DOC_PREFIX)) {
          var startIndex = line.indexOf(DOC_PREFIX) + DOC_PREFIX.length
          var endIndex = line.indexOf("(", startIndex)
          docName = line.slice(startIndex, endIndex)
          
          startIndex = line.indexOf(TRUE_COORD_PREFIX) + TRUE_COORD_PREFIX.length
          endIndex = line.indexOf(")", startIndex)
          val rawCoords = line.slice(startIndex, endIndex).split(",")
          trueCoord = Coordinate.fromDegrees(rawCoords(0).toDouble, rawCoords(1).toDouble)
          None
        }

        else if(line.contains(PRED_COORD_PREFIX)) {
          val startIndex = line.indexOf(PRED_COORD_PREFIX) + PRED_COORD_PREFIX.length
          val endIndex = line.indexOf(")", startIndex)
          val rawCoords = line.slice(startIndex, endIndex).split(",")
          predCoord = Coordinate.fromDegrees(rawCoords(0).toDouble, rawCoords(1).toDouble)

          Some((docName, trueCoord, predCoord))
        }

        else None
      }
      else None
    }).flatten.toList

  }

  import ArgotConverters._

  val parser = new ArgotParser("textgrounder run opennlp.textgrounder.geolocate.ErrorKMLGenerator", preUsage = Some("TextGrounder"))
  val logFile = parser.option[String](List("l", "log"), "log", "log input file")
  val kmlOutFile = parser.option[String](List("k", "kml"), "kml", "kml output file")
  val usePred = parser.option[String](List("p", "pred"), "pred", "show predicted rather than gold locations")

  def main(args: Array[String]) {
    try {
      parser.parse(args)
    }
    catch {
      case e: ArgotUsageException => println(e.message); sys.exit(0)
    }

    if(logFile.value == None) {
      println("You must specify a log input file via -l.")
      sys.exit(0)
    }
    if(kmlOutFile.value == None) {
      println("You must specify a KML output file via -k.")
      sys.exit(0)
    }

    val outFile = new File(kmlOutFile.value.get)
    val stream = new BufferedOutputStream(new FileOutputStream(outFile))
    val out = factory.createXMLStreamWriter(stream, "UTF-8")

    KMLUtil.writeHeader(out, "errors-at-"+(if(usePred.value == None) "true" else "pred"))

    for((docName, trueCoord, predCoord) <- parseLogFile(logFile.value.get)) {
      val dist = trueCoord.distanceInKm(predCoord)

      val coord = if(usePred.value == None) trueCoord else predCoord

      KMLUtil.writePolygon(out, docName, coord, KMLUtil.SIDES, KMLUtil.RADIUS, math.log(dist) * KMLUtil.BARSCALE/2)
    }

    KMLUtil.writeFooter(out)

    out.close
  }
}