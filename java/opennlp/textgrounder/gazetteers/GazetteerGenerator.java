///////////////////////////////////////////////////////////////////////////////
//  Copyright (C) 2010 Taesun Moon, The University of Texas at Austin
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
package opennlp.textgrounder.gazetteers;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.sql.SQLException;
import java.util.logging.Level;
import java.util.logging.Logger;
import opennlp.textgrounder.geo.CommandLineOptions;

/**
 *
 * @author tsmoon
 */
public class GazetteerGenerator {

    /**
     *
     */
    protected static GazetteerEnum.GazetteerTypes gazType;
    /**
     *
     */
    protected static String gazPath;
    protected CommandLineOptions options;

    public GazetteerGenerator(CommandLineOptions options) {
        this.options = options;
        String gazTypeArg = options.getGazetteType().toLowerCase();
        if (gazTypeArg.startsWith("c")) {
            gazType = GazetteerEnum.GazetteerTypes.CG;
        } else if (gazTypeArg.startsWith("n")) {
            gazType = GazetteerEnum.GazetteerTypes.NGAG;
        } else if (gazTypeArg.startsWith("u")) {
            gazType = GazetteerEnum.GazetteerTypes.USGSG;
        } else if (gazTypeArg.startsWith("w")) {
            gazType = GazetteerEnum.GazetteerTypes.WG;
        } else if (gazTypeArg.startsWith("t")) {
            gazType = GazetteerEnum.GazetteerTypes.TRG;
        } else {
            System.err.println("Error: unrecognized gazetteer type: " + gazTypeArg);
            System.err.println("Please enter w, c, u, g, or t.");
            System.exit(0);
            //myGaz = new WGGazetteer();
        }

        gazPath = options.getGazetteerPath();
    }

    public Gazetteer generateGazetteer() {
        Gazetteer gazetteer = null;
        try {
            switch (gazType) {
                case CG:
                    gazetteer = new CensusGazetteer(gazPath);
                    break;
                case NGAG:
                    gazetteer = new NGAGazetteer(gazPath);
                    break;
                case USGSG:
                    gazetteer = new USGSGazetteer(gazPath);
                    break;
                case WG:
                    gazetteer = new WGGazetteer(gazPath);
                    break;
                case TRG:
                    gazetteer = new TRGazetteer(gazPath, options.getGazetteerRefresh());
                    break;
            }
        } catch (FileNotFoundException ex) {
            Logger.getLogger(GazetteerGenerator.class.getName()).log(Level.SEVERE, null, ex);
        } catch (IOException ex) {
            Logger.getLogger(GazetteerGenerator.class.getName()).log(Level.SEVERE, null, ex);
        } catch (ClassNotFoundException ex) {
            Logger.getLogger(GazetteerGenerator.class.getName()).log(Level.SEVERE, null, ex);
        } catch (SQLException ex) {
            Logger.getLogger(GazetteerGenerator.class.getName()).log(Level.SEVERE, null, ex);
        }
        return gazetteer;
    }
}
