"""Dead Island 2 data for the launcher: enemies (one entry per archetype: Walker, Shambler, Runner,
bee swarm walker) and the models that can go on them (Runner/Walker/Shambler meshes, both sexes,
all on SKEL_ZombieStandard; special looks such as burning or hazmat are left out).

Sources (built earlier from the game's packages, see tools/): data/variants.json (Walker/Shambler
variations -> variants -> mesh), data/variant_map.json (the Walker/Shambler variants that can be
swapped: special looks such as burning, fuel tank or riot gear are left out), data/runner_variants.json
(Runner variations; "excluded" = special runners), data/insect_variants.json (bee swarm walkers).
"""
import json
import re
from collections import OrderedDict

SPECIAL_MESH = re.compile(r"Burning|Fireman|Hazmat|Caustic|Corrosive|Shock|Electric|Spiky|Vicious|Loot|Satchel|"
                          r"FuelTank|Grenade|Riot|InsectSwarm", re.I)
EXTRA_WOMEN = {"SK_Amanda_Styles_Runner": "/Game/DI2/Art/Characters/Cine/SK_Amanda_Styles_Runner"}
SECTIONS = (("walker", "Walkers"), ("shambler", "Shamblers"), ("runner", "Runners"), ("insect", "Bee swarm walkers"))
ACTS = (("all", "whole game + DLCs · special zombies keep their look"),)
PRETTY = {"Filmset": "Film set", "CDC": "CDC", "LAPD": "LAPD", "WW2": "WW2", "Med": "Medical", "Haus": "Haus",
          "PalmTree": "SoLA", "CulDeSac": "Cul-de-sac", "MainHall": "Main hall", "CasualFestival": "Festival",
          "VIP": "VIP", "Base": "Generic", "Pizza": "Pizza (turtles)", "CorpseAcid": "Corpse acid",
          "InsectSwarm": "Bee swarm"}


def short(path):
    return path.rsplit("/", 1)[1]


def words(s):
    if s in PRETTY:
        return PRETTY[s]
    return " ".join(split_words(s))


def theme_of(variation):
    """DA_ModelVariation_Walker_Casual_Alessa -> ("walker", "Casual"); named one-offs join their theme."""
    n = variation.replace("DA_ModelVariation_", "")
    if n.startswith("Base"):
        return n[4:].lower(), "Base"
    parts = n.split("_")
    arch, rest = parts[0].lower(), parts[1:]
    if not rest:
        return arch, "Base"
    t = rest[0]
    if t.startswith("InsectSwarm"):
        return "insect", "InsectSwarm"
    if t.startswith("Pizza"):
        return arch, "Pizza"
    if t in ("Haus", "PalmTree") and len(rest) > 1:
        return arch, f"{t}_{rest[1]}"
    return arch, t


ABBREV = {"Cas": "Casual", "Sec": "Security", "Med": "Medical", "Swim": "Swimwear", "Filmset": "Film set",
          "Cul": "Cul-de-sac", "Deep": "Deeper", "Spr": "Spring break", "Lrg": "Large", "Hal": "Halperin",
          "Life": "Lifeguard", "Wed": "Wedding", "Spid": "Spider", "Named": "Named", "Mili": "Military"}
ARCH = {"Runner": "Runner", "Walker": "Walker", "Sham": "Shambler", "Shambler": "Shambler"}


def split_words(s):
    return re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Za-z])|(?<=[A-Z])(?=[0-9])|(?<=[A-Z])(?=[A-Z][a-z])",
                  " ", s).split()


TABS = ("Runner", "Walker", "Shambler")


def parse_model(mesh):
    """SK_RunnerFemSwim05 -> ("Runner", "F", ["Swimwear", "05"], ""); SK_ShamFemEx1Cas02 ->
    ("Shambler", "F", ["Casual", "02"], " (Haus)"). Archetype None = not a Runner/Walker/Shambler mesh."""
    if mesh in EXTRA_WOMEN:
        return "Runner", "F", split_words(mesh[3:].replace("_Runner", "").replace("_", " ")), ""
    n = mesh[3:] if mesh.startswith("SK_") else mesh
    m = re.match(r"(Runner|Walker|Shambler|Sham)(Female|Fem|Male)?(.+)$", n)
    if not m or SPECIAL_MESH.search(mesh):
        return None, None, [], ""
    arch, tag, rest = ARCH[m.group(1)], m.group(2), m.group(3)
    sex = "F" if tag in ("Female", "Fem") else "M" if tag == "Male" else None
    dlc = ""
    ex = re.search(r"Ex([12])(?=[0-9A-Z]|$)", rest)
    if ex:
        dlc, rest = (" (Haus)" if ex.group(1) == "1" else " (SoLA)"), rest[:ex.start()] + rest[ex.end():]
    rest = re.sub(r"Film[Ss]et", "Filmset", rest).replace("_", " ")
    words_ = [w for w in split_words(rest) if w not in ("Fem", "Female")]
    for i in range(len(words_) - 1):   # "WW" "2" -> "WW2"
        if words_[i] == "WW" and words_[i + 1] == "2":
            words_[i:i + 2] = ["WW2"]
            break
    return arch, sex, [ABBREV.get(w, w) for w in words_], dlc


class Catalog:
    def __init__(self, data_dir):
        load = lambda n: json.load(open(f"{data_dir}/{n}", encoding="utf-8"))
        variants, vmap = load("variants.json"), load("variant_map.json")
        runners, insects = load("runner_variants.json"), load("insect_variants.json")
        eligible = set(vmap["variant_map"])

        self.mesh_of = {}        # variant -> mesh package path
        meshes = {}              # mesh short name -> package path (every zombie mesh we know)
        female = {}              # mesh short name -> True/False, from the variant data
        enemies = OrderedDict()  # archetype -> {"arch", "variations": set, "variants": set}

        def know(mesh, is_female):
            if mesh:
                meshes[short(mesh)] = mesh
                if is_female is not None:
                    female[short(mesh)] = bool(is_female)

        def add(variation, variant, mesh):
            arch, _theme = theme_of(variation)
            key = arch  # one entry per archetype (themes were too many for the list)
            e = enemies.setdefault(key, {"arch": arch, "variations": set(), "variants": set()})
            e["variations"].add(variation)
            e["variants"].add(variant)
            self.mesh_of[variant] = mesh

        for variation, entries in variants["variations"].items():
            for v in entries:
                know(v["mesh"], True if v.get("female") else False if v.get("male") else None)
                if v["variant"] in insects:
                    add(variation, v["variant"], insects[v["variant"]])
                elif v["variant"] in eligible:
                    add(variation, v["variant"], v["mesh"])
        for v in variants.get("female_runners", []):
            know(v["mesh"], True)
        excluded = set(runners["excluded"])
        for variation, names in runners["variations"].items():
            for x in names:
                v = runners["variants"].get(x)
                if not v or not v["mesh"]:
                    continue
                know(v["mesh"], v.get("female"))
                if x not in excluded:
                    add(variation, x, v["mesh"])
        meshes.update(EXTRA_WOMEN)

        self.enemies = enemies
        # models = Runner/Walker/Shambler meshes whose sex is known (special looks left out)
        self.models, self._info = {}, {}
        for m, path in meshes.items():
            arch, sex, words_, dlc = parse_model(m)
            sex = "F" if female.get(m) else "M" if m in female else sex
            if m in EXTRA_WOMEN:
                sex = "F"
            if arch and sex and words_:
                self.models[m] = path
                self._info[m] = (arch, sex, words_, dlc)

    # ---------- views for the UI ----------
    def enemy_name(self, key):
        return dict(SECTIONS)[key]

    def enemy_acts(self, key):
        return ["all"]

    def categories(self):
        return [("Zombies", [arch for arch, _ in SECTIONS if arch in self.enemies])]

    def model_list(self):
        """(key, name in the list, tab, group) - tab = the model's archetype, group = outfit
        (Casual, Army, Swimwear...; outfits with a single model go under "Other")."""
        rows = []
        for m, (arch, sex, w, dlc) in self._info.items():
            rows.append((m, f"{sex}_{' '.join(w)}{dlc}", arch, w[0] if not w[0].isdigit() else "Other"))
        sizes = {}
        for _, _, tab, g in rows:
            sizes[(tab, g)] = sizes.get((tab, g), 0) + 1
        rows = [(k, n, t, g if sizes[(t, g)] > 1 else "Other") for k, n, t, g in rows]
        rows.sort(key=lambda r: (TABS.index(r[2]), r[3] == "Other", r[3], r[1]))
        return rows

    def chip_name(self, m):
        """Name on the enemy's chip: keeps the archetype (F_Runner Swimwear 05)."""
        arch, sex, w, dlc = self._info[m]
        return f"{sex}_{arch} {' '.join(w)}{dlc}"

    # ---------- what the patcher and the UE4SS mod need ----------
    def swaps(self, chosen, shuffle=None):
        """chosen: {enemy key: [model keys]} -> the swap list. Several models on one enemy are dealt
        out in turn over its variants, so they all appear mixed in the game; `shuffle` (e.g.
        random.shuffle) changes which variant gets which model at every Apply."""
        swaps, base = {}, set()  # a variant listed in several variations gets one model
        for key, models in chosen.items():
            if not models or key not in self.enemies:
                continue
            variants = sorted(self.enemies[key]["variants"])
            if shuffle:
                shuffle(variants)
            for i, x in enumerate(variants):
                target = self.models[models[i % len(models)]]
                if self.mesh_of[x] != target:
                    swaps[x] = [x, self.mesh_of[x], target]
                    if self.enemies[key]["arch"] in ("walker", "shambler"):
                        base.add(x)
        return {"swaps": list(swaps.values()), "base_count": len(base & set(swaps))}

    def mod_classes(self, chosen):
        """Blueprint class (lower case) -> [models], for the mod's mannequin repair; plus per archetype."""
        classes, archs = {}, {}
        for key, models in chosen.items():
            if not models or key not in self.enemies:
                continue
            e = self.enemies[key]
            for model in models:
                for variation in e["variations"]:
                    cls = "bp_" + variation.replace("DA_ModelVariation_", "").lower() + "_c"
                    classes.setdefault(cls, [])
                    if model not in classes[cls]:
                        classes[cls].append(model)
                archs.setdefault(e["arch"], [])
                if model not in archs[e["arch"]]:
                    archs[e["arch"]].append(model)
        return classes, archs
