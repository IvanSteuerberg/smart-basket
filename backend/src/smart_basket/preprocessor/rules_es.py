"""General Spanish rules of the preprocessor: abbreviations, units, numbers, connectors,
ambiguity markers and a small synonym list. Language knowledge only; product vocabulary
comes from the lexicon, and personal vocabulary will live per user in the browser.

All keys are folded (lower case, no accents), as produced by `text.fold`.
"""

from decimal import Decimal

from smart_basket.preprocessor.lexicon import UnitTerm

#: Token-level abbreviations and shorthand seen in real lists.
ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    "d": ("de",),
    "dl": ("del",),
    "semi": ("semidesnatada",),
    "semidesn": ("semidesnatada",),
    "desn": ("desnatada",),
    "integ": ("integral",),
    "s/": ("sin",),
    "c/": ("con",),
    "aove": ("aceite", "de", "oliva", "virgen", "extra"),
    "aov": ("aceite", "de", "oliva", "virgen"),
    "ph": ("papel", "higienico"),
    "yog": ("yogur",),
    "yogs": ("yogures",),
    "choco": ("chocolate",),
    "pq": ("paquete",),
    "paq": ("paquete",),
    "paqs": ("paquetes",),
    "uds": ("ud",),
    "unid": ("ud",),
    "unids": ("ud",),
    "lt": ("l",),
    "lts": ("l",),
    "ltr": ("l",),
    "gr": ("g",),
    "grs": ("g",),
    "grms": ("g",),
    "kgs": ("kg",),
    "kls": ("kg",),
    "doc": ("docena",),
    "bot": ("botella",),
}

#: Measures and containers. Containers count units ("2 paquetes" is 2 ud).
UNITS: tuple[UnitTerm, ...] = (
    *(
        UnitTerm(f, "kg", Decimal(1))
        for f in ("kg", "k", "kilo", "kilos", "kilogramo", "kilogramos")
    ),
    *(UnitTerm(f, "g", Decimal(1)) for f in ("g", "gramo", "gramos")),
    *(UnitTerm(f, "l", Decimal(1)) for f in ("l", "litro", "litros")),
    *(UnitTerm(f, "ml", Decimal(1)) for f in ("ml", "mililitro", "mililitros")),
    *(UnitTerm(f, "ml", Decimal(10)) for f in ("cl", "centilitro", "centilitros")),
    *(UnitTerm(f, "ud", Decimal(12)) for f in ("docena", "docenas")),
    *(UnitTerm(f, "ud", Decimal(1)) for f in ("ud", "unidad", "unidades", "pieza", "piezas")),
    *(
        UnitTerm(f, "ud", Decimal(1), container=True)
        for f in (
            "paquete",
            "paquetes",
            "pack",
            "packs",
            "bote",
            "botes",
            "lata",
            "latas",
            "brick",
            "bricks",
            "brik",
            "briks",
            "tetrabrik",
            "tetrabriks",
            "botella",
            "botellas",
            "botellin",
            "botellines",
            "caja",
            "cajas",
            "tarro",
            "tarros",
            "bolsa",
            "bolsas",
            "sobre",
            "sobres",
            "barra",
            "barras",
            "tableta",
            "tabletas",
            "malla",
            "mallas",
            "bandeja",
            "bandejas",
            "rollo",
            "rollos",
            "tarrina",
            "tarrinas",
            "garrafa",
            "garrafas",
            "frasco",
            "frascos",
            "tubo",
            "tubos",
            "manojo",
            "manojos",
        )
    ),
)

NUMBER_WORDS: dict[str, Decimal] = {
    "un": Decimal(1),
    "uno": Decimal(1),
    "una": Decimal(1),
    "dos": Decimal(2),
    "tres": Decimal(3),
    "cuatro": Decimal(4),
    "cinco": Decimal(5),
    "seis": Decimal(6),
    "siete": Decimal(7),
    "ocho": Decimal(8),
    "nueve": Decimal(9),
    "diez": Decimal(10),
    "once": Decimal(11),
    "doce": Decimal(12),
    "quince": Decimal(15),
    "veinte": Decimal(20),
    "treinta": Decimal(30),
}

#: Fractions used before a unit: "medio kilo", "un cuarto de kilo", "tres cuartos de litro".
FRACTION_WORDS: dict[str, Decimal] = {
    "medio": Decimal("0.5"),
    "media": Decimal("0.5"),
    "cuarto": Decimal("0.25"),
    "cuartos": Decimal("0.25"),
}

#: Multipliers between two numbers: "6x1,5 l", "6 por 1,5 l".
MULTIPLIERS = frozenset({"x", "×", "por"})

#: Words that join content words and never decide a match on their own.
CONNECTORS = frozenset(
    {"de", "del", "para", "con", "en", "al", "a", "y", "e", "el", "la", "los", "las"}
)

#: Words dropped when left over after matching.
FILLERS = frozenset(
    {
        *CONNECTORS,
        "un",
        "una",
        "unos",
        "unas",
        "o",
        "u",
        "tambien",
        "mas",
        "porfa",
        "favor",
        "por",
        "poco",
        "pocos",
        "poca",
        "pocas",
        "bien",
        "bueno",
        "buena",
        "buenos",
        "buenas",
    }
)

#: A line with any of these needs the LLM (or the user) to decide what to buy.
AMBIGUITY_WORDS = frozenset(
    {
        "algo",
        "cosa",
        "cosas",
        "alguna",
        "alguno",
        "algunas",
        "algunos",
        "algun",
        "rico",
        "rica",
        "ricos",
        "ricas",
        "variado",
        "variada",
        "variados",
        "variadas",
        "etc",
        "necesario",
    }
)
AMBIGUITY_PHRASES: tuple[tuple[str, ...], ...] = (
    ("lo", "de", "siempre"),
    ("lo", "que"),
    ("lo", "necesario"),
    ("lo", "habitual"),
)

#: Purpose words: "para el desayuno", "para el finde" give context, not a product.
PURPOSE_WORDS = frozenset(
    {
        "desayuno",
        "desayunos",
        "comida",
        "comidas",
        "cena",
        "cenas",
        "merienda",
        "almuerzo",
        "aperitivo",
        "picar",
        "finde",
        "semana",
        "fiesta",
        "cumple",
        "cumpleanos",
        "sabado",
        "domingo",
        "viernes",
        "noche",
        "manana",
        "tarde",
        "amigos",
        "invitados",
        "ninos",
        "casa",
        "familia",
        "fin",
        "barbacoa",
        "navidad",
    }
)

#: Small general synonym list (folded word sequences). Regional and spelling variants only.
SYNONYMS: dict[tuple[str, ...], tuple[str, ...]] = {
    ("jugo",): ("zumo",),
    ("jugos",): ("zumos",),
    ("yogurt",): ("yogur",),
    ("yogurts",): ("yogures",),
    ("yoghurt",): ("yogur",),
    ("yogourt",): ("yogur",),
    ("olivas",): ("aceitunas",),
    ("spaghetti",): ("espaguetis",),
    ("spaghettis",): ("espaguetis",),
    ("espagueti",): ("espaguetis",),
    ("ketchup",): ("tomate", "ketchup"),
    ("patatas", "chips"): ("patatas", "fritas"),
    ("papel", "de", "wc"): ("papel", "higienico"),
    ("papel", "wc"): ("papel", "higienico"),
    ("papel", "de", "bano"): ("papel", "higienico"),
    ("detergente", "lavadora"): ("detergente", "para", "lavadora"),
    ("crema", "de", "dientes"): ("pasta", "de", "dientes"),
    ("dentifrico",): ("pasta", "de", "dientes"),
    ("cuchillas", "de", "afeitar"): ("maquinillas", "de", "afeitar"),
    ("papas", "fritas"): ("patatas", "fritas"),
}
