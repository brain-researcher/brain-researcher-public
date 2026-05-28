"""Atlas lookups and coordinate utilities for neuroimaging spatial queries."""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Atlas dictionary mapping ROI names to centroid coordinates.
# Keys are atlas names, values are dictionaries of ROI name (lower case) -> [x,y,z]
# Coordinates are given in their native space.
# ----------------------------------------------------------------------------
_ATLAS_COORDS: dict[str, dict[str, list[float]]] = {
    "MNI": {
        # Common anatomical regions
        "insula": [36.0, 18.0, 6.0],
        "left_insula": [-36.0, 18.0, 6.0],
        "right_insula": [36.0, 18.0, 6.0],
        "hippocampus": [26.0, -20.0, -12.0],
        "left_hippocampus": [-26.0, -20.0, -12.0],
        "right_hippocampus": [26.0, -20.0, -12.0],
        "amygdala": [24.0, -4.0, -18.0],
        "left_amygdala": [-24.0, -4.0, -18.0],
        "right_amygdala": [24.0, -4.0, -18.0],
        "thalamus": [10.0, -18.0, 8.0],
        "left_thalamus": [-10.0, -18.0, 8.0],
        "right_thalamus": [10.0, -18.0, 8.0],
        "caudate": [12.0, 12.0, 8.0],
        "left_caudate": [-12.0, 12.0, 8.0],
        "right_caudate": [12.0, 12.0, 8.0],
        "putamen": [24.0, 4.0, 2.0],
        "left_putamen": [-24.0, 4.0, 2.0],
        "right_putamen": [24.0, 4.0, 2.0],
        # Brodmann areas
        "ba44": [-50.0, 15.0, 20.0],  # Broca's area (pars opercularis)
        "ba45": [-48.0, 30.0, 14.0],  # Broca's area (pars triangularis)
        "ba4": [-38.0, -20.0, 58.0],  # Primary motor cortex
        "ba6": [-24.0, -4.0, 54.0],  # Premotor cortex
        "ba17": [-8.0, -88.0, 4.0],  # Primary visual cortex
        "ba41": [-42.0, -32.0, 12.0],  # Primary auditory cortex
        "ba1": [-42.0, -26.0, 54.0],  # Primary somatosensory cortex
        "ba2": [-38.0, -30.0, 50.0],  # Primary somatosensory cortex
        "ba3": [-40.0, -24.0, 56.0],  # Primary somatosensory cortex
        # Major cortical regions
        "prefrontal_cortex": [30.0, 40.0, 30.0],
        "dorsolateral_prefrontal_cortex": [40.0, 30.0, 30.0],
        "dlpfc": [40.0, 30.0, 30.0],  # Alias
        "ventromedial_prefrontal_cortex": [4.0, 50.0, -8.0],
        "vmpfc": [4.0, 50.0, -8.0],  # Alias
        "anterior_cingulate_cortex": [4.0, 35.0, 20.0],
        "acc": [4.0, 35.0, 20.0],  # Alias
        "posterior_cingulate_cortex": [4.0, -45.0, 25.0],
        "pcc": [4.0, -45.0, 25.0],  # Alias
        # Temporal regions
        "superior_temporal_gyrus": [55.0, -20.0, 4.0],
        "stg": [55.0, -20.0, 4.0],  # Alias
        "middle_temporal_gyrus": [55.0, -35.0, -5.0],
        "mtg": [55.0, -35.0, -5.0],  # Alias
        "inferior_temporal_gyrus": [50.0, -30.0, -20.0],
        "itg": [50.0, -30.0, -20.0],  # Alias
        "fusiform_gyrus": [40.0, -50.0, -15.0],
        # Parietal regions
        "superior_parietal_lobule": [25.0, -60.0, 55.0],
        "spl": [25.0, -60.0, 55.0],  # Alias
        "inferior_parietal_lobule": [45.0, -45.0, 45.0],
        "ipl": [45.0, -45.0, 45.0],  # Alias
        "precuneus": [7.0, -60.0, 40.0],
        "angular_gyrus": [45.0, -60.0, 35.0],
        "supramarginal_gyrus": [55.0, -35.0, 35.0],
        # Frontal regions
        "superior_frontal_gyrus": [20.0, 35.0, 45.0],
        "middle_frontal_gyrus": [35.0, 30.0, 35.0],
        "inferior_frontal_gyrus": [48.0, 20.0, 20.0],
        "precentral_gyrus": [40.0, -15.0, 50.0],
        "postcentral_gyrus": [40.0, -30.0, 50.0],
        # Occipital regions
        "occipital_pole": [15.0, -95.0, 5.0],
        "lingual_gyrus": [15.0, -70.0, -5.0],
        "cuneus": [10.0, -80.0, 25.0],
        # Subcortical structures
        "brainstem": [0.0, -25.0, -15.0],
        "cerebellum": [20.0, -55.0, -25.0],
        "pallidum": [18.0, 0.0, 0.0],
        "left_pallidum": [-18.0, 0.0, 0.0],
        "right_pallidum": [18.0, 0.0, 0.0],
    },
    "Talairach": {
        # Selected regions with Talairach coordinates
        "insula": [34.0, 16.0, 4.0],
        "hippocampus": [25.0, -19.0, -11.0],
        "amygdala": [23.0, -4.0, -17.0],
        "ba44": [-48.0, 14.0, 18.0],
        "ba45": [-46.0, 28.0, 13.0],
        "thalamus": [9.0, -17.0, 7.0],
        "caudate": [11.0, 11.0, 7.0],
        "putamen": [23.0, 4.0, 2.0],
    },
    "AAL": {
        # Automated Anatomical Labeling atlas regions (subset)
        "precentral_l": [-38.0, -6.0, 51.0],
        "precentral_r": [41.0, -8.0, 52.0],
        "frontal_sup_l": [-18.0, 35.0, 42.0],
        "frontal_sup_r": [22.0, 31.0, 44.0],
        "frontal_mid_l": [-33.0, 33.0, 35.0],
        "frontal_mid_r": [38.0, 33.0, 34.0],
        "frontal_inf_oper_l": [-48.0, 13.0, 19.0],
        "frontal_inf_oper_r": [50.0, 15.0, 20.0],
        "frontal_inf_tri_l": [-46.0, 30.0, 14.0],
        "frontal_inf_tri_r": [48.0, 32.0, 14.0],
        "rolandic_oper_l": [-48.0, -8.0, 14.0],
        "rolandic_oper_r": [52.0, -6.0, 14.0],
        "supp_motor_area_l": [-5.0, 5.0, 61.0],
        "supp_motor_area_r": [8.0, 0.0, 62.0],
        "hippocampus_l": [-25.0, -21.0, -10.0],
        "hippocampus_r": [29.0, -21.0, -10.0],
        "amygdala_l": [-23.0, -1.0, -17.0],
        "amygdala_r": [27.0, 1.0, -17.0],
    },
    "HarvardOxford": {
        # Harvard-Oxford atlas regions (subset)
        "frontal_pole": [30.0, 55.0, 15.0],
        "insular_cortex": [35.0, 10.0, 0.0],
        "superior_frontal_gyrus": [15.0, 30.0, 50.0],
        "middle_frontal_gyrus": [35.0, 25.0, 40.0],
        "inferior_frontal_gyrus_pars_triangularis": [48.0, 30.0, 15.0],
        "inferior_frontal_gyrus_pars_opercularis": [50.0, 15.0, 20.0],
        "precentral_gyrus": [35.0, -10.0, 50.0],
        "temporal_pole": [35.0, 10.0, -30.0],
        "superior_temporal_gyrus_anterior": [55.0, -5.0, -10.0],
        "superior_temporal_gyrus_posterior": [60.0, -30.0, 10.0],
        "hippocampus": [25.0, -20.0, -12.0],
        "amygdala": [22.0, -5.0, -18.0],
        "thalamus": [10.0, -18.0, 8.0],
        "caudate": [12.0, 12.0, 8.0],
        "putamen": [24.0, 4.0, 2.0],
        "pallidum": [18.0, 0.0, 0.0],
    },
    "Yeo7": {
        # Yeo 7-network parcellation (Yeo et al., 2011)
        # Network centroids based on typical network locations
        "visual": [0.0, -75.0, 10.0],
        "somatomotor": [0.0, -20.0, 65.0],
        "dorsal_attention": [25.0, -60.0, 50.0],
        "ventral_attention": [50.0, -45.0, 25.0],
        "limbic": [0.0, -25.0, -10.0],
        "frontoparietal": [40.0, 50.0, 20.0],
        "default": [0.0, -60.0, 35.0],
        # Common aliases
        "visual_network": [0.0, -75.0, 10.0],
        "somatomotor_network": [0.0, -20.0, 65.0],
        "dorsal_attention_network": [25.0, -60.0, 50.0],
        "ventral_attention_network": [50.0, -45.0, 25.0],
        "limbic_network": [0.0, -25.0, -10.0],
        "frontoparietal_network": [40.0, 50.0, 20.0],
        "default_mode_network": [0.0, -60.0, 35.0],
        "dmn": [0.0, -60.0, 35.0],  # DMN alias
        "dan": [25.0, -60.0, 50.0],  # DAN alias
        "van": [50.0, -45.0, 25.0],  # VAN alias
        "fpn": [40.0, 50.0, 20.0],  # FPN alias
    },
    "Yeo17": {
        # Yeo 17-network parcellation (finer-grained version)
        # Visual networks
        "visual_a": [-20.0, -80.0, 10.0],
        "visual_b": [20.0, -70.0, 10.0],
        # Somatomotor networks
        "somatomotor_a": [0.0, -20.0, 65.0],
        "somatomotor_b": [-55.0, -10.0, 20.0],
        # Dorsal attention networks
        "dorsal_attention_a": [25.0, -60.0, 50.0],
        "dorsal_attention_b": [-25.0, -60.0, 50.0],
        # Ventral attention networks
        "salience_ventral_attention_a": [50.0, -45.0, 25.0],
        "salience_ventral_attention_b": [35.0, 20.0, 0.0],
        # Limbic networks
        "limbic_a": [0.0, -25.0, -10.0],
        "limbic_b": [25.0, -40.0, -20.0],
        # Control networks
        "control_a": [45.0, 35.0, 30.0],
        "control_b": [-45.0, 35.0, 30.0],
        "control_c": [0.0, 35.0, 45.0],
        # Default networks
        "default_a": [0.0, -60.0, 35.0],
        "default_b": [0.0, 50.0, -10.0],
        "default_c": [-45.0, -70.0, 35.0],
        # Temporal-parietal
        "temporal_parietal": [-55.0, -50.0, 15.0],
    },
    "Schaefer400": {
        # Schaefer 400-parcel atlas (subset of key regions)
        # These are example parcels - full atlas has 400 regions
        # Visual network parcels
        "vis_1": [-10.0, -90.0, 5.0],
        "vis_2": [10.0, -90.0, 5.0],
        "vis_3": [-25.0, -85.0, 20.0],
        "vis_4": [25.0, -85.0, 20.0],
        # Somatomotor parcels
        "sommat_1": [-40.0, -20.0, 55.0],
        "sommat_2": [40.0, -20.0, 55.0],
        "sommat_3": [0.0, -15.0, 70.0],
        # Dorsal attention parcels
        "dorsattn_1": [-25.0, -55.0, 55.0],
        "dorsattn_2": [25.0, -55.0, 55.0],
        "dorsattn_3": [-30.0, -40.0, 45.0],
        "dorsattn_4": [30.0, -40.0, 45.0],
        # Ventral attention parcels
        "ventattn_1": [-45.0, -40.0, 20.0],
        "ventattn_2": [45.0, -40.0, 20.0],
        "ventattn_3": [-55.0, -25.0, 10.0],
        "ventattn_4": [55.0, -25.0, 10.0],
        # Limbic parcels
        "limbic_1": [-5.0, -15.0, -15.0],
        "limbic_2": [5.0, -15.0, -15.0],
        "limbic_3": [-20.0, -25.0, -20.0],
        "limbic_4": [20.0, -25.0, -20.0],
        # Frontoparietal parcels
        "fronto_1": [-35.0, 45.0, 25.0],
        "fronto_2": [35.0, 45.0, 25.0],
        "fronto_3": [-45.0, 15.0, 35.0],
        "fronto_4": [45.0, 15.0, 35.0],
        # Default mode parcels
        "default_1": [0.0, -55.0, 30.0],
        "default_2": [-5.0, 50.0, -5.0],
        "default_3": [-45.0, -65.0, 35.0],
        "default_4": [45.0, -65.0, 35.0],
        # Add more parcels as needed...
    },
    "Power264": {
        # Power 264-node atlas (subset of key nodes)
        # Nodes are grouped by functional networks
        # Default mode network nodes
        "dmn_mpfc": [1.0, 55.0, -3.0],
        "dmn_pcc": [1.0, -61.0, 38.0],
        "dmn_lp_l": [-46.0, -68.0, 35.0],
        "dmn_lp_r": [46.0, -68.0, 35.0],
        # Fronto-parietal network nodes
        "fpn_lpfc_l": [-43.0, 33.0, 28.0],
        "fpn_lpfc_r": [43.0, 33.0, 28.0],
        "fpn_ppc_l": [-46.0, -58.0, 49.0],
        "fpn_ppc_r": [46.0, -58.0, 49.0],
        # Cingulo-opercular network nodes
        "co_ains_l": [-35.0, 14.0, 5.0],
        "co_ains_r": [35.0, 14.0, 5.0],
        "co_dacc": [0.0, 21.0, 36.0],
        # Dorsal attention network nodes
        "dan_fef_l": [-27.0, -9.0, 56.0],
        "dan_fef_r": [27.0, -9.0, 56.0],
        "dan_ips_l": [-39.0, -43.0, 52.0],
        "dan_ips_r": [39.0, -43.0, 52.0],
        # Ventral attention network nodes
        "van_tpj_l": [-51.0, -47.0, 24.0],
        "van_tpj_r": [51.0, -47.0, 24.0],
        "van_vfc_r": [50.0, 26.0, 2.0],
        # Visual network nodes
        "vis_v1": [0.0, -86.0, 6.0],
        "vis_mt_l": [-45.0, -69.0, -2.0],
        "vis_mt_r": [45.0, -69.0, -2.0],
        # Sensorimotor network nodes
        "sm_m1_l": [-37.0, -25.0, 57.0],
        "sm_m1_r": [37.0, -25.0, 57.0],
        "sm_s1_l": [-40.0, -27.0, 53.0],
        "sm_s1_r": [40.0, -27.0, 53.0],
    },
    "Gordon333": {
        # Gordon 333-parcel atlas (subset)
        # Based on Gordon et al., 2016 Cerebral Cortex
        # Default mode network
        "default_pcc": [0.0, -52.0, 30.0],
        "default_mpfc": [0.0, 52.0, 2.0],
        "default_ag_l": [-44.0, -66.0, 36.0],
        "default_ag_r": [44.0, -66.0, 36.0],
        # Fronto-parietal network
        "fp_dlpfc_l": [-44.0, 36.0, 26.0],
        "fp_dlpfc_r": [44.0, 36.0, 26.0],
        "fp_ips_l": [-32.0, -56.0, 48.0],
        "fp_ips_r": [32.0, -56.0, 48.0],
        # Cingulo-opercular network
        "co_acc": [0.0, 22.0, 34.0],
        "co_ains_l": [-32.0, 22.0, 4.0],
        "co_ains_r": [32.0, 22.0, 4.0],
        # Dorsal attention network
        "da_fef_l": [-24.0, -8.0, 52.0],
        "da_fef_r": [24.0, -8.0, 52.0],
        "da_mt_l": [-48.0, -72.0, 2.0],
        "da_mt_r": [48.0, -72.0, 2.0],
        # Ventral attention network
        "va_tpj_l": [-52.0, -48.0, 26.0],
        "va_tpj_r": [52.0, -48.0, 26.0],
        # Visual network
        "vis_v1": [0.0, -88.0, 4.0],
        "vis_v2_l": [-14.0, -92.0, 12.0],
        "vis_v2_r": [14.0, -92.0, 12.0],
        # Sensorimotor network
        "sm_cs_hand": [0.0, -16.0, 66.0],
        "sm_cs_face_l": [-54.0, -8.0, 32.0],
        "sm_cs_face_r": [54.0, -8.0, 32.0],
        # Auditory network
        "aud_stg_l": [-58.0, -22.0, 10.0],
        "aud_stg_r": [58.0, -22.0, 10.0],
    },
}

# Available atlases
AVAILABLE_ATLASES = list(_ATLAS_COORDS.keys())


def get_roi_coordinates(roi_name: str, atlas: str = "MNI") -> list[float] | None:
    """Return centroid coordinates for an ROI in the given atlas.

    Parameters
    ----------
    roi_name : str
        Common name for the region of interest (case-insensitive).
    atlas : str
        Name of atlas defining the ROI coordinates. Default is "MNI".
        Available atlases: MNI, Talairach, AAL, HarvardOxford

    Returns
    -------
    Optional[List[float]]
        [x, y, z] coordinates if ROI is found, None otherwise.
    """
    atlas_dict = _ATLAS_COORDS.get(atlas)
    if not atlas_dict:
        logger.warning(
            f"Atlas '{atlas}' not found. Available atlases: {AVAILABLE_ATLASES}"
        )
        return None

    # Convert to lowercase for case-insensitive lookup
    roi_lower = roi_name.lower()
    coords = atlas_dict.get(roi_lower)

    if coords is None:
        # Try to find partial matches
        partial_matches = [
            k for k in atlas_dict.keys() if roi_lower in k or k in roi_lower
        ]
        if partial_matches:
            logger.info(
                f"ROI '{roi_name}' not found in {atlas}. Similar ROIs: {partial_matches[:5]}"
            )
        else:
            logger.warning(f"ROI '{roi_name}' not found in {atlas} atlas")

    return coords


def list_available_rois(atlas: str = "MNI") -> list[str]:
    """List all available ROIs in the specified atlas.

    Parameters
    ----------
    atlas : str
        Name of atlas. Default is "MNI".

    Returns
    -------
    List[str]
        List of available ROI names, empty list if atlas not found.
    """
    atlas_dict = _ATLAS_COORDS.get(atlas, {})
    return sorted(list(atlas_dict.keys()))


def talairach_to_mni(coords: list[float], method: str = "lancaster") -> list[float]:
    """Convert Talairach coordinates to MNI space.

    Parameters
    ----------
    coords : List[float]
        [x, y, z] coordinates in Talairach space.
    method : str
        Transformation method: "lancaster" (default) or "brett"

    Returns
    -------
    List[float]
        [x, y, z] coordinates in MNI space.
    """
    x, y, z = coords

    if method == "lancaster":
        # Lancaster et al. (2007) transform
        return [
            1.0100 * x,
            1.0000 * y - 0.0460 * z,
            0.0485 * y + 1.0810 * z,
        ]
    elif method == "brett":
        # Matthew Brett transform (mni2tal)
        # Approximate inverse of MNI to Talairach
        return [
            0.9900 * x,
            0.9688 * y + 0.0460 * z,
            -0.0485 * y + 0.9189 * z,
        ]
    else:
        raise ValueError(f"Unknown transformation method: {method}")


def mni_to_talairach(coords: list[float], method: str = "lancaster") -> list[float]:
    """Convert MNI coordinates to Talairach space.

    Parameters
    ----------
    coords : List[float]
        [x, y, z] coordinates in MNI space.
    method : str
        Transformation method: "lancaster" (default) or "brett"

    Returns
    -------
    List[float]
        [x, y, z] coordinates in Talairach space.
    """
    x, y, z = coords

    if method == "lancaster":
        # Inverse of Lancaster et al. (2007) transform
        return [
            0.9900 * x,
            0.9688 * y + 0.0460 * z,
            -0.0485 * y + 0.9189 * z,
        ]
    elif method == "brett":
        # Matthew Brett transform (tal2mni)
        return [
            1.0100 * x,
            1.0000 * y - 0.0460 * z,
            0.0485 * y + 1.0810 * z,
        ]
    else:
        raise ValueError(f"Unknown transformation method: {method}")


def euclidean_distance(coord1: list[float], coord2: list[float]) -> float:
    """Calculate Euclidean distance between two coordinates.

    Parameters
    ----------
    coord1 : List[float]
        First [x, y, z] coordinate.
    coord2 : List[float]
        Second [x, y, z] coordinate.

    Returns
    -------
    float
        Euclidean distance in mm.
    """
    return math.sqrt(
        sum((c1 - c2) ** 2 for c1, c2 in zip(coord1, coord2, strict=False))
    )


def overlap_score(
    coord: list[float],
    roi_name: str,
    atlas: str = "MNI",
    method: str = "gaussian",
    sigma: float = 10.0,
    roi_radius: float = 15.0,
) -> float:
    """Calculate probabilistic overlap score between a coordinate and an ROI.

    Parameters
    ----------
    coord : List[float]
        Coordinate in the same space as the atlas.
    roi_name : str
        ROI to compare against.
    atlas : str
        Atlas in which the ROI is defined.
    method : str
        Scoring method: "gaussian" (default) or "sphere"
    sigma : float
        Spread parameter for Gaussian model in mm (default: 10.0)
    roi_radius : float
        Radius for sphere model in mm (default: 15.0)

    Returns
    -------
    float
        Overlap score between 0 and 1, where 1 indicates perfect overlap.
    """
    target = get_roi_coordinates(roi_name, atlas)
    if target is None:
        return 0.0

    dist = euclidean_distance(coord, target)

    if method == "gaussian":
        # Gaussian decay based on distance
        return math.exp(-(dist**2) / (2.0 * sigma**2))
    elif method == "sphere":
        # Binary sphere model with smooth edge
        if dist <= roi_radius:
            return 1.0
        elif dist <= roi_radius * 1.5:
            # Smooth transition zone
            return 1.0 - (dist - roi_radius) / (roi_radius * 0.5)
        else:
            return 0.0
    else:
        raise ValueError(f"Unknown overlap method: {method}")


def find_nearby_rois(
    coord: list[float],
    atlas: str = "MNI",
    radius: float = 20.0,
    top_k: int | None = None,
) -> list[tuple[str, float]]:
    """Find ROIs within a certain distance of a coordinate.

    Parameters
    ----------
    coord : List[float]
        [x, y, z] coordinate to search around.
    atlas : str
        Atlas to search in.
    radius : float
        Search radius in mm.
    top_k : Optional[int]
        Return only top k closest ROIs. If None, return all within radius.

    Returns
    -------
    List[Tuple[str, float]]
        List of (roi_name, distance) tuples, sorted by distance.
    """
    atlas_dict = _ATLAS_COORDS.get(atlas, {})
    if not atlas_dict:
        logger.warning(f"Atlas '{atlas}' not found")
        return []

    nearby_rois = []
    for roi_name, roi_coord in atlas_dict.items():
        dist = euclidean_distance(coord, roi_coord)
        if dist <= radius:
            nearby_rois.append((roi_name, dist))

    # Sort by distance
    nearby_rois.sort(key=lambda x: x[1])

    if top_k is not None:
        nearby_rois = nearby_rois[:top_k]

    return nearby_rois


def validate_coordinates(coords: list[float], space: str = "MNI") -> tuple[bool, str]:
    """Validate that coordinates are within reasonable bounds for the space.

    Parameters
    ----------
    coords : List[float]
        [x, y, z] coordinates to validate.
    space : str
        Coordinate space: "MNI" or "Talairach"

    Returns
    -------
    Tuple[bool, str]
        (is_valid, message) where is_valid is True if coordinates are reasonable,
        and message provides details if not valid.
    """
    if len(coords) != 3:
        return False, f"Coordinates must have 3 values, got {len(coords)}"

    x, y, z = coords

    if space == "MNI":
        # MNI space bounds (approximate)
        if not (-90 <= x <= 90):
            return False, f"X coordinate {x} outside MNI bounds [-90, 90]"
        if not (-126 <= y <= 91):
            return False, f"Y coordinate {y} outside MNI bounds [-126, 91]"
        if not (-72 <= z <= 109):
            return False, f"Z coordinate {z} outside MNI bounds [-72, 109]"
    elif space == "Talairach":
        # Talairach space bounds (approximate)
        if not (-80 <= x <= 80):
            return False, f"X coordinate {x} outside Talairach bounds [-80, 80]"
        if not (-120 <= y <= 80):
            return False, f"Y coordinate {y} outside Talairach bounds [-120, 80]"
        if not (-70 <= z <= 85):
            return False, f"Z coordinate {z} outside Talairach bounds [-70, 85]"
    else:
        return False, f"Unknown coordinate space: {space}"

    return True, "Coordinates are valid"
