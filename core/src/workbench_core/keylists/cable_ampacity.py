# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Current carrying capacity (ampacity) of Nexans Olex low voltage power cables, from the
Nexans Olex Handbook 2017, "Current Ratings" section (IEC 60287 calculations).

Basis printed in the handbook: air ambient 40 °C; maximum conductor temperature 80 °C for XLPE
and 75 °C for PVC; direct sunlight 1000 W/m²; 1.0 m/s wind. Derating for other conditions is in
AS/NZS 3008.1 (not reproduced in the handbook). The buried-direct and underground-duct columns
are not used: the handbook does not state the ground basis for them.

Only copper and only the four in-air methods are kept. Values are the handbook's, transcribed
from each page by reading its word positions and checked against the printed page. The
"verified" note says how far each table was checked against the page image:
  image          every value compared with the rendered page
  partly checked the rows that were compared matched; the rest was checked by count and order only
  not checked   read by the same method; not yet compared with the page
"""

from __future__ import annotations

#: Method keys: unenclosed_space, spaced_from_surface (single cores only), touching, enclosed_conduit_in_air.
METHODS: dict[str, str] = {
    "unenclosed_space": "Unenclosed in air",
    "spaced_from_surface": "Spaced from surface",
    "touching": "Touching",
    "enclosed_conduit_in_air": "Enclosed in conduit in air",
}

#: Each table: key -> (title, page, insulation, cores, flexible, verified, {method: {size mm²: amps}}).
TABLES: dict[str, dict] = {
    "1C-PVC": {
        "title": "1 core V-90 PVC (solid)", "page": 61, "insulation": "PVC", "cores": "1C",
        "flexible": False, "verified": "image",
        "amps": {
            "unenclosed_space": {"1": 16, "1.5": 21, "2.5": 30, "4": 40, "6": 51, "10": 69, "16": 92, "25": 124, "35": 153, "50": 187, "70": 238, "95": 295, "120": 344, "150": 395, "185": 459, "240": 549, "300": 636, "400": 744, "500": 867, "630": 1014},
            "spaced_from_surface": {"1": 16, "1.5": 21, "2.5": 29, "4": 39, "6": 49, "10": 67, "16": 89, "25": 119, "35": 145, "50": 177, "70": 223, "95": 276, "120": 321, "150": 367, "185": 424, "240": 505, "300": 582, "400": 676, "500": 780, "630": 897},
            "touching": {"1": 13, "1.5": 16, "2.5": 23, "4": 31, "6": 40, "10": 54, "16": 72, "25": 97, "35": 119, "50": 146, "70": 184, "95": 230, "120": 267, "150": 308, "185": 358, "240": 428, "300": 495, "400": 577, "500": 668, "630": 770},
            "enclosed_conduit_in_air": {"1": 13, "1.5": 18, "2.5": 24, "4": 32, "6": 41, "10": 54, "16": 70, "25": 94, "35": 112, "50": 138, "70": 170, "95": 212, "120": 242, "150": 282, "185": 320, "240": 381},
        },
    },
    "1C-PVC-flex": {
        "title": "1 core V-90 PVC (flexible)", "page": 62, "insulation": "PVC", "cores": "1C",
        "flexible": True, "verified": "image",
        "amps": {
            "unenclosed_space": {"1": 17, "1.5": 21, "2.5": 29, "4": 38, "6": 49, "10": 69, "16": 91, "25": 121, "35": 150, "50": 189, "70": 238, "95": 287, "120": 341, "150": 393, "185": 450, "240": 541, "300": 624, "400": 752, "500": 876, "630": 1036},
            "spaced_from_surface": {"1": 17, "1.5": 21, "2.5": 28, "4": 38, "6": 48, "10": 67, "16": 88, "25": 115, "35": 143, "50": 179, "70": 224, "95": 269, "120": 317, "150": 365, "185": 416, "240": 498, "300": 571, "400": 682, "500": 787, "630": 914},
            "touching": {"1": 13, "1.5": 17, "2.5": 22, "4": 30, "6": 38, "10": 54, "16": 71, "25": 94, "35": 117, "50": 147, "70": 185, "95": 223, "120": 265, "150": 306, "185": 351, "240": 422, "300": 486, "400": 583, "500": 675, "630": 785},
            "enclosed_conduit_in_air": {"1": 14, "1.5": 18, "2.5": 24, "4": 31, "6": 40, "10": 54, "16": 69, "25": 91, "35": 110, "50": 139, "70": 169, "95": 206, "120": 237, "150": 278, "185": 312, "240": 373},
        },
    },
    "1C-XLPE": {
        "title": "1 core XLPE/PVC (solid)", "page": 63, "insulation": "XLPE", "cores": "1C",
        "flexible": False, "verified": "image",
        "amps": {
            "unenclosed_space": {"1": 20, "1.5": 26, "2.5": 36, "4": 48, "6": 61, "10": 84, "16": 112, "25": 151, "35": 186, "50": 228, "70": 291, "95": 361, "120": 422, "150": 486, "185": 565, "240": 678, "300": 787, "400": 923, "500": 1078, "630": 1261},
            "spaced_from_surface": {"1": 20, "1.5": 25, "2.5": 36, "4": 47, "6": 60, "10": 82, "16": 108, "25": 145, "35": 177, "50": 216, "70": 273, "95": 338, "120": 393, "150": 451, "185": 522, "240": 622, "300": 718, "400": 836, "500": 966, "630": 1113},
            "touching": {"1": 16, "1.5": 20, "2.5": 28, "4": 37, "6": 47, "10": 65, "16": 86, "25": 117, "35": 144, "50": 176, "70": 224, "95": 278, "120": 325, "150": 375, "185": 436, "240": 522, "300": 605, "400": 708, "500": 821, "630": 950},
            "enclosed_conduit_in_air": {"1": 16, "1.5": 21, "2.5": 30, "4": 38, "6": 47, "10": 65, "16": 84, "25": 113, "35": 135, "50": 166, "70": 204, "95": 255, "120": 292, "150": 329, "185": 387, "240": 461},
        },
    },
    "1C-XLPE-flex": {
        "title": "1 core XLPE/PVC (flexible)", "page": 64, "insulation": "XLPE", "cores": "1C",
        "flexible": True, "verified": "not checked",
        "amps": {
            "unenclosed_space": {"1": 21, "1.5": 26, "2.5": 35, "4": 46, "6": 59, "10": 83, "16": 110, "25": 147, "35": 183, "50": 231, "70": 292, "95": 351, "120": 418, "150": 483, "185": 555, "240": 668, "300": 772, "400": 933, "500": 1090, "630": 1288},
            "spaced_from_surface": {"1": 21, "1.5": 26, "2.5": 34, "4": 46, "6": 58, "10": 81, "16": 106, "25": 141, "35": 174, "50": 218, "70": 274, "95": 328, "120": 389, "150": 448, "185": 512, "240": 613, "300": 705, "400": 843, "500": 975, "630": 1135},
            "touching": {"1": 16, "1.5": 20, "2.5": 27, "4": 36, "6": 46, "10": 64, "16": 85, "25": 114, "35": 141, "50": 178, "70": 225, "95": 271, "120": 322, "150": 373, "185": 428, "240": 515, "300": 594, "400": 715, "500": 830, "630": 969},
            "enclosed_conduit_in_air": {"1": 17, "1.5": 21, "2.5": 28, "4": 37, "6": 46, "10": 64, "16": 82, "25": 109, "35": 132, "50": 167, "70": 204, "95": 248, "120": 286, "150": 336, "185": 377, "240": 452},
        },
    },
    "2C-PVC": {
        "title": "2 core V-90 PVC", "page": 67, "insulation": "PVC", "cores": "2C",
        "flexible": False, "verified": "partly checked",
        "amps": {
            "unenclosed_space": {"1": 15, "1.5": 19, "2.5": 27, "4": 37, "6": 46, "10": 64, "16": 85, "25": 113, "35": 139, "50": 170, "70": 215, "95": 265, "120": 307, "150": 351, "185": 403, "240": 477, "300": 547, "400": 631, "500": 716},
            "touching": {"1": 14, "1.5": 18, "2.5": 26, "4": 34, "6": 44, "10": 60, "16": 80, "25": 107, "35": 131, "50": 159, "70": 201, "95": 248, "120": 288, "150": 328, "185": 377, "240": 446, "300": 511, "400": 589, "500": 668},
            "enclosed_conduit_in_air": {"1": 13, "1.5": 16, "2.5": 23, "4": 30, "6": 39, "10": 52, "16": 68, "25": 90, "35": 112, "50": 133, "70": 170, "95": 204, "120": 241, "150": 271, "185": 313, "240": 364, "300": 424, "400": 482, "500": 561},
        },
    },
    "2C-XLPE": {
        "title": "2 core XLPE/PVC", "page": 69, "insulation": "XLPE", "cores": "2C",
        "flexible": False, "verified": "not checked",
        "amps": {
            "unenclosed_space": {"1": 18, "1.5": 24, "2.5": 34, "4": 45, "6": 57, "10": 78, "16": 104, "25": 140, "35": 173, "50": 211, "70": 268, "95": 331, "120": 385, "150": 441, "185": 509, "240": 604, "300": 694, "400": 804, "500": 915},
            "touching": {"1": 17, "1.5": 22, "2.5": 31, "4": 42, "6": 53, "10": 73, "16": 97, "25": 131, "35": 162, "50": 197, "70": 250, "95": 309, "120": 359, "150": 411, "185": 473, "240": 562, "300": 645, "400": 745, "500": 848},
            "enclosed_conduit_in_air": {"1": 16, "1.5": 20, "2.5": 28, "4": 37, "6": 46, "10": 63, "16": 82, "25": 110, "35": 132, "50": 162, "70": 200, "95": 250, "120": 285, "150": 332, "185": 377, "240": 448, "300": 523, "400": 596, "500": 695},
        },
    },
    "3C4C-PVC": {
        "title": "3 and 4 core V-90 PVC", "page": 78, "insulation": "PVC", "cores": "3C/4C",
        "flexible": False, "verified": "partly checked",
        "amps": {
            "unenclosed_space": {"1": 13, "1.5": 16, "2.5": 23, "4": 31, "6": 40, "10": 54, "16": 72, "25": 97, "35": 120, "50": 146, "70": 185, "95": 228, "120": 265, "150": 303, "185": 348, "240": 412, "300": 472, "400": 544, "500": 616},
            "touching": {"1": 12, "1.5": 15, "2.5": 22, "4": 29, "6": 37, "10": 51, "16": 68, "25": 91, "35": 112, "50": 137, "70": 172, "95": 213, "120": 247, "150": 282, "185": 324, "240": 383, "300": 438, "400": 504, "500": 571},
            "enclosed_conduit_in_air": {"1": 11, "1.5": 14, "2.5": 20, "4": 25, "6": 33, "10": 44, "16": 58, "25": 76, "35": 94, "50": 112, "70": 142, "95": 177, "120": 202, "150": 228, "185": 263, "240": 316},
        },
    },
    "3C4C-XLPE": {
        "title": "3 and 4 core XLPE/PVC", "page": 80, "insulation": "XLPE", "cores": "3C/4C",
        "flexible": False, "verified": "partly checked",
        "amps": {
            "unenclosed_space": {"1": 16, "1.5": 20, "2.5": 28, "4": 38, "6": 48, "10": 66, "16": 88, "25": 119, "35": 147, "50": 180, "70": 229, "95": 283, "120": 330, "150": 377, "185": 436, "240": 517, "300": 594, "400": 685, "500": 779},
            "touching": {"1": 14, "1.5": 19, "2.5": 26, "4": 35, "6": 45, "10": 62, "16": 83, "25": 111, "35": 137, "50": 168, "70": 213, "95": 263, "120": 306, "150": 350, "185": 404, "240": 479, "300": 549, "400": 632, "500": 718},
            "enclosed_conduit_in_air": {"1": 13, "1.5": 16, "2.5": 24, "4": 30, "6": 38, "10": 53, "16": 68, "25": 91, "35": 114, "50": 136, "70": 173, "95": 209, "120": 246, "150": 277, "185": 322, "240": 386},
        },
    },
}


def ampacity(table: str, size: str) -> dict[str, int]:
    """The copper amps of a conductor size (mm², as text: "1.5", "630") in each in-air method
    the table prints for it. Empty when the table has no such size."""
    t = TABLES[table]
    return {m: v[size] for m, v in t["amps"].items() if size in v}


__all__ = ["METHODS", "TABLES", "ampacity"]
