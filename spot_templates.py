"""Terrain generation templates, one per fishing spot.

Each config drives UnderwaterMap._generate_from_config() to produce a
distinct underwater layout so every spot has a unique personality.

Keys
----
label           : one-line description shown in-game
depth_profile   : "bowl" | "flat" | "flat_shallow" | "slope" | "shelf"
break_lines     : number of depth-break horizontal bands
weed_patches    : how many weed clusters to scatter
weed_density    : 0-1 fill probability within a patch radius
cover_clusters  : sunken-wood / brush clusters
cover_density   : fill probability
rock_clusters   : rock-pile clusters
rock_density    : fill probability
bait_count      : random baitfish cells placed
"""

SPOT_CONFIGS: dict = {
    "North Point": {
        "label": "Rocky point – depth breaks",
        "depth_profile": "slope",
        "break_lines": 2,
        "weed_patches": 1, "weed_density": 0.40,
        "cover_clusters": 1, "cover_density": 0.50,
        "rock_clusters": 3, "rock_density": 0.65,
        "bait_count": 12,
    },
    "NE Weed Flat": {
        "label": "Dense weed flat – bait magnet",
        "depth_profile": "flat_shallow",
        "break_lines": 0,
        "weed_patches": 6, "weed_density": 0.78,
        "cover_clusters": 0, "cover_density": 0.00,
        "rock_clusters": 0, "rock_density": 0.00,
        "bait_count": 35,
    },
    "East Shore": {
        "label": "Mixed bank – beginner friendly",
        "depth_profile": "bowl",
        "break_lines": 1,
        "weed_patches": 2, "weed_density": 0.55,
        "cover_clusters": 2, "cover_density": 0.50,
        "rock_clusters": 1, "rock_density": 0.40,
        "bait_count": 20,
    },
    "SE Cove": {
        "label": "Fallen trees – cover heaven",
        "depth_profile": "flat",
        "break_lines": 0,
        "weed_patches": 1, "weed_density": 0.30,
        "cover_clusters": 5, "cover_density": 0.75,
        "rock_clusters": 0, "rock_density": 0.00,
        "bait_count": 15,
    },
    "South Flat": {
        "label": "Open flat – low structure",
        "depth_profile": "flat",
        "break_lines": 0,
        "weed_patches": 1, "weed_density": 0.30,
        "cover_clusters": 0, "cover_density": 0.00,
        "rock_clusters": 1, "rock_density": 0.30,
        "bait_count": 8,
    },
    "SW Brush": {
        "label": "Heavy brush – ambush zone",
        "depth_profile": "flat",
        "break_lines": 1,
        "weed_patches": 2, "weed_density": 0.50,
        "cover_clusters": 4, "cover_density": 0.80,
        "rock_clusters": 0, "rock_density": 0.00,
        "bait_count": 18,
    },
    "West Bank": {
        "label": "Rocky bank – scattered breaks",
        "depth_profile": "slope",
        "break_lines": 2,
        "weed_patches": 1, "weed_density": 0.35,
        "cover_clusters": 1, "cover_density": 0.40,
        "rock_clusters": 4, "rock_density": 0.55,
        "bait_count": 14,
    },
    "NW Drop-off": {
        "label": "Sharp shelf – depth fishing",
        "depth_profile": "shelf",
        "break_lines": 3,
        "weed_patches": 0, "weed_density": 0.00,
        "cover_clusters": 1, "cover_density": 0.50,
        "rock_clusters": 2, "rock_density": 0.50,
        "bait_count": 8,
    },
    "Island Point": {
        "label": "Diverse structure – all fish sizes",
        "depth_profile": "bowl",
        "break_lines": 1,
        "weed_patches": 3, "weed_density": 0.60,
        "cover_clusters": 2, "cover_density": 0.55,
        "rock_clusters": 2, "rock_density": 0.50,
        "bait_count": 28,
    },
    "Rock Pile": {
        "label": "Dense rocks – trophy spot",
        "depth_profile": "bowl",
        "break_lines": 1,
        "weed_patches": 0, "weed_density": 0.00,
        "cover_clusters": 1, "cover_density": 0.40,
        "rock_clusters": 6, "rock_density": 0.80,
        "bait_count": 22,
    },
}

DEFAULT_CONFIG: dict = {
    "label": "Generic spot",
    "depth_profile": "bowl",
    "break_lines": 1,
    "weed_patches": 2, "weed_density": 0.50,
    "cover_clusters": 1, "cover_density": 0.50,
    "rock_clusters": 1, "rock_density": 0.40,
    "bait_count": 15,
}
