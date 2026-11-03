"""Original icon geometry on a 64x64 grid.

Each icon is a list of primitives tagged with a role:
  body   - the main silhouette (filled in 'filled'/'duotone' styles)
  detail - inner lines (stroked; knocked out in white in 'filled' style)
Everything here is hand-built from basic shapes, so it is original work you own.
"""
from __future__ import annotations

import math

P = dict  # primitive


def _gear(cx=32, cy=32, r_out=22, r_in=16, teeth=8) -> str:
    pts = []
    for i in range(teeth * 4):
        a = 2 * math.pi * i / (teeth * 4)
        r = r_out if (i % 4) in (1, 2) else r_in
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pts)


def _star(cx=32, cy=33, r1=23, r2=10, n=5) -> str:
    pts = []
    for i in range(n * 2):
        a = -math.pi / 2 + math.pi * i / n
        r = r1 if i % 2 == 0 else r2
        pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    return " ".join(pts)


def _rays(cx=32, cy=32, r1=16, r2=24, n=8, offset=0.0) -> list[P]:
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n + offset
        out.append(P(t="line", role="detail", x1=cx + r1 * math.cos(a), y1=cy + r1 * math.sin(a),
                     x2=cx + r2 * math.cos(a), y2=cy + r2 * math.sin(a)))
    return out


def _blade(angle: float) -> P:
    return P(t="path", role="body", d="M32 28 C29 20 30 10 32 4 C34 10 35 20 32 28 Z",
             transform=f"rotate({angle} 32 28)")


ICONS: dict[str, list[P]] = {
    "home": [P(t="path", role="body", d="M10 30 L32 11 L54 30 V54 H10 Z"),
             P(t="rect", role="detail", x=27, y=38, w=10, h=16, r=1)],
    "briefcase": [P(t="rect", role="body", x=9, y=22, w=46, h=31, r=4),
                  P(t="path", role="detail", d="M24 22 V15 H40 V22"),
                  P(t="line", role="detail", x1=9, y1=34, x2=55, y2=34)],
    "bar_chart": [P(t="rect", role="body", x=13, y=36, w=9, h=18, r=1.5),
                  P(t="rect", role="body", x=27.5, y=24, w=9, h=30, r=1.5),
                  P(t="rect", role="body", x=42, y=12, w=9, h=42, r=1.5),
                  P(t="line", role="detail", x1=8, y1=56, x2=56, y2=56)],
    "pie_chart": [P(t="circle", role="body", cx=32, cy=32, r=22),
                  P(t="path", role="detail", d="M32 32 V10 M32 32 L51 43")],
    "target": [P(t="circle", role="body", cx=32, cy=32, r=22),
               P(t="circle", role="detail", cx=32, cy=32, r=13),
               P(t="circle", role="detail", cx=32, cy=32, r=4)],
    "lightbulb": [P(t="path", role="body", d="M32 7 C20 7 14 17 16 27 C18 35 24 38 24 45 H40 C40 38 46 35 48 27 C50 17 44 7 32 7 Z"),
                  P(t="line", role="detail", x1=25, y1=51, x2=39, y2=51),
                  P(t="line", role="detail", x1=28, y1=57, x2=36, y2=57)],
    "calendar": [P(t="rect", role="body", x=9, y=13, w=46, h=42, r=4),
                 P(t="line", role="detail", x1=9, y1=25, x2=55, y2=25),
                 P(t="line", role="detail", x1=21, y1=8, x2=21, y2=17),
                 P(t="line", role="detail", x1=43, y1=8, x2=43, y2=17),
                 P(t="circle", role="detail", cx=21, cy=35, r=1.5), P(t="circle", role="detail", cx=32, cy=35, r=1.5),
                 P(t="circle", role="detail", cx=43, cy=35, r=1.5), P(t="circle", role="detail", cx=21, cy=45, r=1.5),
                 P(t="circle", role="detail", cx=32, cy=45, r=1.5)],
    "mail": [P(t="rect", role="body", x=8, y=15, w=48, h=34, r=3),
             P(t="path", role="detail", d="M9 18 L32 36 L55 18")],
    "user": [P(t="circle", role="body", cx=32, cy=21, r=11),
             P(t="path", role="body", d="M11 56 C11 42 21 35 32 35 C43 35 53 42 53 56 Z")],
    "gear": [P(t="poly", role="body", points=_gear()),
             P(t="circle", role="detail", cx=32, cy=32, r=7)],
    "document": [P(t="path", role="body", d="M15 7 H40 L50 17 V57 H15 Z"),
                 P(t="path", role="detail", d="M40 7 V17 H50"),
                 P(t="line", role="detail", x1=22, y1=29, x2=43, y2=29),
                 P(t="line", role="detail", x1=22, y1=37, x2=43, y2=37),
                 P(t="line", role="detail", x1=22, y1=45, x2=35, y2=45)],
    "wallet": [P(t="rect", role="body", x=8, y=17, w=48, h=36, r=5),
               P(t="rect", role="detail", x=38, y=28, w=18, h=14, r=3),
               P(t="circle", role="detail", cx=45, cy=35, r=1.8)],
    "megaphone": [P(t="path", role="body", d="M9 26 H20 L44 13 V51 L20 38 H9 Z"),
                  P(t="path", role="detail", d="M17 38 L21 52 H28 L25 38"),
                  P(t="path", role="detail", d="M50 23 L56 19 M50 32 H58 M50 41 L56 45")],
    "clock": [P(t="circle", role="body", cx=32, cy=32, r=23),
              P(t="path", role="detail", d="M32 17 V32 L42 38")],
    "lock": [P(t="path", role="detail", d="M21 28 V20 A11 11 0 0 1 43 20 V28"),
             P(t="rect", role="body", x=13, y=28, w=38, h=28, r=4),
             P(t="path", role="detail", d="M32 38 V46")],
    "shield": [P(t="path", role="body", d="M32 7 L52 15 V30 C52 44 42 52 32 57 C22 52 12 44 12 30 V15 Z"),
               P(t="path", role="detail", d="M22 32 L29 39 L43 25")],
    "cloud": [P(t="path", role="body", d="M18 47 H47 A11 11 0 0 0 46 25 A15 15 0 0 0 19 28 A9.5 9.5 0 0 0 18 47 Z")],
    "globe": [P(t="circle", role="body", cx=32, cy=32, r=23),
              P(t="ellipse", role="detail", cx=32, cy=32, rx=10, ry=23),
              P(t="path", role="detail", d="M9 32 H55 M13 21 H51 M13 43 H51")],
    "leaf": [P(t="path", role="body", d="M12 52 C12 25 30 11 54 11 C54 36 40 52 12 52 Z"),
             P(t="path", role="detail", d="M12 52 L42 23")],
    "sun": [P(t="circle", role="body", cx=32, cy=32, r=11)] + _rays(),
    "drop": [P(t="path", role="body", d="M32 7 C32 7 13 30 13 40 A19 19 0 0 0 51 40 C51 30 32 7 32 7 Z"),
             P(t="path", role="detail", d="M23 40 A9 9 0 0 0 32 49")],
    "tree": [P(t="rect", role="body", x=29, y=36, w=6, h=20, r=1),
             P(t="circle", role="body", cx=32, cy=24, r=17),
             P(t="line", role="detail", x1=20, y1=57, x2=44, y2=57)],
    "battery": [P(t="rect", role="body", x=7, y=19, w=45, h=26, r=4),
                P(t="rect", role="body", x=52, y=27, w=5, h=10, r=1.5),
                P(t="path", role="detail", d="M32 23 L25 33 H35 L28 42")],
    "solar_panel": [P(t="path", role="body", d="M8 42 L16 14 H56 L48 42 Z"),
                    P(t="path", role="detail", d="M12 28 H52 M29 14 L23 42 M43 14 L37 42"),
                    P(t="path", role="detail", d="M30 42 V54 M20 55 H40")],
    "wind_turbine": [P(t="line", role="detail", x1=32, y1=30, x2=32, y2=58),
                     _blade(0), _blade(120), _blade(240),
                     P(t="circle", role="body", cx=32, cy=28, r=3.5)],
    "plant": [P(t="path", role="detail", d="M32 40 V22"),
              P(t="path", role="body", d="M32 30 C23 30 18 23 18 15 C27 15 32 22 32 30 Z"),
              P(t="path", role="body", d="M32 25 C40 25 46 19 46 11 C38 11 32 17 32 25 Z"),
              P(t="path", role="body", d="M18 40 H46 L42 57 H22 Z")],
    "map_pin": [P(t="path", role="body", d="M32 57 C32 57 13 37 13 25 A19 19 0 0 1 51 25 C51 37 32 57 32 57 Z"),
                P(t="circle", role="detail", cx=32, cy=25, r=7)],
    "suitcase": [P(t="path", role="detail", d="M24 19 V12 H40 V19"),
                 P(t="rect", role="body", x=12, y=19, w=40, h=34, r=4),
                 P(t="path", role="detail", d="M22 19 V53 M42 19 V53"),
                 P(t="circle", role="body", cx=20, cy=57, r=2.5), P(t="circle", role="body", cx=44, cy=57, r=2.5)],
    "camera": [P(t="path", role="body", d="M8 23 A4 4 0 0 1 12 19 H21 L25 12 H39 L43 19 H52 A4 4 0 0 1 56 23 V49 A4 4 0 0 1 52 53 H12 A4 4 0 0 1 8 49 Z"),
               P(t="circle", role="detail", cx=32, cy=35, r=10),
               P(t="circle", role="detail", cx=48, cy=26, r=1.5)],
    "compass": [P(t="circle", role="body", cx=32, cy=32, r=23),
                P(t="poly", role="detail", points="32,14 37,32 32,50 27,32"),
                P(t="line", role="detail", x1=27, y1=32, x2=37, y2=32)],
    "ticket": [P(t="path", role="body", d="M8 18 H56 V27 A5 5 0 0 0 56 37 V46 H8 V37 A5 5 0 0 0 8 27 Z"),
               P(t="path", role="detail", d="M41 21 V25 M41 30 V34 M41 39 V43")],
    "palm_tree": [P(t="path", role="detail", d="M33 57 C34 45 33 35 30 25"),
                  P(t="path", role="body", d="M30 25 C24 15 14 14 7 19 C15 18 23 20 30 25 Z"),
                  P(t="path", role="body", d="M30 25 C36 14 47 12 56 17 C47 17 38 19 30 25 Z"),
                  P(t="path", role="body", d="M30 25 C22 25 15 31 13 39 C19 32 25 28 30 25 Z"),
                  P(t="path", role="body", d="M30 25 C38 24 46 29 49 37 C43 31 36 28 30 25 Z"),
                  P(t="line", role="detail", x1=20, y1=57, x2=46, y2=57)],
    "plane": [P(t="path", role="body", d="M32 6 C35 6 36 10 36 14 V25 L56 37 V43 L36 36 V48 L42 53 V57 L32 54 L22 57 V53 L28 48 V36 L8 43 V37 L28 25 V14 C28 10 29 6 32 6 Z")],
    "three_wheeler": [P(t="path", role="body", d="M9 45 V29 C9 21 15 16 23 16 H43 C50 16 55 22 55 30 V45 Z"),
                      P(t="path", role="detail", d="M9 31 H55 M30 16 V45"),
                      P(t="circle", role="body", cx=17, cy=48, r=5.5), P(t="circle", role="body", cx=47, cy=48, r=5.5)],
    "lantern": [P(t="line", role="detail", x1=32, y1=3, x2=32, y2=10),
                P(t="poly", role="body", points="32,10 47,19 47,38 32,48 17,38 17,19"),
                P(t="path", role="detail", d="M17 19 L32 29 L47 19 M32 29 V48 M17 38 L32 29 L47 38"),
                P(t="path", role="detail", d="M25 44 L23 58 M32 48 V60 M39 44 L41 58")],
    "oil_lamp": [P(t="path", role="body", d="M32 12 C38 20 38 28 32 31 C26 28 26 20 32 12 Z"),
                 P(t="line", role="detail", x1=32, y1=31, x2=32, y2=38),
                 P(t="path", role="body", d="M9 38 H55 C53 48 43 53 32 53 C21 53 11 48 9 38 Z")],
    "lotus": [P(t="path", role="body", d="M32 50 C23 40 23 23 32 12 C41 23 41 40 32 50 Z"),
              P(t="path", role="body", d="M32 50 C21 49 11 40 8 27 C19 27 28 36 32 50 Z"),
              P(t="path", role="body", d="M32 50 C43 49 53 40 56 27 C45 27 36 36 32 50 Z"),
              P(t="line", role="detail", x1=14, y1=55, x2=50, y2=55)],
    "gift": [P(t="rect", role="body", x=12, y=27, w=40, h=28, r=2),
             P(t="rect", role="body", x=9, y=19, w=46, h=9, r=2),
             P(t="path", role="detail", d="M32 19 V55 M32 19 C26 9 17 13 23 19 M32 19 C38 9 47 13 41 19")],
    "star": [P(t="poly", role="body", points=_star())],
    "heart": [P(t="path", role="body", d="M32 55 C14 43 7 33 7 23 A12.5 12.5 0 0 1 32 17 A12.5 12.5 0 0 1 57 23 C57 33 50 43 32 55 Z")],
    "candle": [P(t="path", role="body", d="M32 8 C37 15 37 21 32 24 C27 21 27 15 32 8 Z"),
               P(t="rect", role="body", x=25, y=28, w=14, h=26, r=2),
               P(t="line", role="detail", x1=20, y1=57, x2=44, y2=57)],
    "fireworks": _rays(32, 32, 7, 22, 12) + [P(t="circle", role="body", cx=32, cy=32, r=4)]
                 + [P(t="circle", role="body", cx=32 + 26 * math.cos(a), cy=32 + 26 * math.sin(a), r=2)
                    for a in [i * math.pi / 3 for i in range(6)]],
    "drum": [P(t="path", role="body", d="M12 22 V44 C12 50 52 50 52 44 V22 Z"),
             P(t="ellipse", role="detail", cx=32, cy=22, rx=20, ry=6),
             P(t="path", role="detail", d="M12 30 L20 46 L28 31 L36 47 L44 31 L52 44")],
    "teacup": [P(t="path", role="detail", d="M45 28 H50 A6 6 0 0 1 50 40 H44"),
               P(t="path", role="body", d="M11 24 H46 V35 C46 46 38 52 28.5 52 C19 52 11 46 11 35 Z"),
               P(t="path", role="detail", d="M21 17 C19 13 23 11 21 7 M30 17 C28 13 32 11 30 7 M39 17 C37 13 41 11 39 7")],
    "bowl": [P(t="path", role="body", d="M13 32 C17 23 47 23 51 32 Z"),
             P(t="path", role="body", d="M7 32 H57 C55 45 45 52 32 52 C19 52 9 45 7 32 Z"),
             P(t="line", role="detail", x1=24, y1=57, x2=40, y2=57)],
    "chili": [P(t="path", role="detail", d="M51 18 C51 12 55 9 58 8"),
              P(t="path", role="body", d="M13 51 C30 51 48 39 52 18 C46 27 30 40 11 42 C9 46 9 51 13 51 Z")],
    "coconut": [P(t="circle", role="body", cx=32, cy=34, r=21),
                P(t="circle", role="detail", cx=25, cy=27, r=2.2), P(t="circle", role="detail", cx=37, cy=27, r=2.2),
                P(t="circle", role="detail", cx=31, cy=36, r=2.2)],
    "cart": [P(t="path", role="detail", d="M7 11 H15 L22 41 H50 L55 19 H17"),
             P(t="circle", role="body", cx=26, cy=50, r=4.5), P(t="circle", role="body", cx=46, cy=50, r=4.5)],
    "wifi": [P(t="path", role="detail", d="M10 27 A31 31 0 0 1 54 27 M18 35 A19 19 0 0 1 46 35 M26 43 A8 8 0 0 1 38 43"),
             P(t="circle", role="body", cx=32, cy=51, r=3.5)],
    "smartphone": [P(t="rect", role="body", x=18, y=5, w=28, h=54, r=5),
                   P(t="line", role="detail", x1=28, y1=11, x2=36, y2=11),
                   P(t="circle", role="detail", cx=32, cy=52, r=2)],
    "laptop": [P(t="rect", role="body", x=13, y=13, w=38, h=27, r=3),
               P(t="path", role="body", d="M5 45 H59 L55 52 H9 Z"),
               P(t="line", role="detail", x1=26, y1=48.5, x2=38, y2=48.5)],
    "search": [P(t="circle", role="body", cx=27, cy=27, r=15),
               P(t="line", role="detail", x1=38, y1=38, x2=54, y2=54),
               P(t="circle", role="detail", cx=27, cy=27, r=8)],
    "medical_cross": [P(t="path", role="body", d="M25 9 H39 V25 H55 V39 H39 V55 H25 V39 H9 V25 H25 Z")],
    "pill": [P(t="rect", role="body", x=10, y=24, w=44, h=16, r=8, transform="rotate(-35 32 32)"),
             P(t="line", role="detail", x1=32, y1=24, x2=32, y2=40, transform="rotate(-35 32 32)")],
    "graduation_cap": [P(t="path", role="body", d="M17 32 V43 C17 48 25 51 32 51 C39 51 47 48 47 43 V32"),
                       P(t="poly", role="body", points="32,13 59,26 32,39 5,26"),
                       P(t="path", role="detail", d="M53 29 V42")],
    "book": [P(t="path", role="body", d="M7 14 C15 11 24 11 31 17 V54 C24 48 15 48 7 50 Z"),
             P(t="path", role="body", d="M57 14 C49 11 40 11 33 17 V54 C40 48 49 48 57 50 Z")],
}

ICON_SETS: dict[str, dict] = {
    "business": {"topic": "small business and entrepreneurship",
                 "icons": ["briefcase", "bar_chart", "pie_chart", "target", "lightbulb", "calendar",
                           "mail", "user", "gear", "document", "wallet", "megaphone"]},
    "technology": {"topic": "technology and ai concepts",
                   "icons": ["smartphone", "laptop", "cloud", "wifi", "lock", "shield", "globe", "search",
                             "gear", "battery", "clock", "mail"]},
    "ecology": {"topic": "sustainability and renewable energy",
                "icons": ["leaf", "sun", "drop", "tree", "battery", "solar_panel", "plant", "globe",
                          "wind_turbine", "cloud", "lightbulb", "heart"]},
    "travel": {"topic": "travel and tourism",
               "icons": ["plane", "suitcase", "map_pin", "camera", "compass", "ticket", "palm_tree", "sun",
                         "globe", "three_wheeler", "clock", "home"]},
    "festival": {"topic": "south asian festivals and rituals",
                 "icons": ["lantern", "oil_lamp", "lotus", "gift", "star", "heart", "candle", "fireworks",
                           "drum", "calendar", "sun", "teacup"]},
    "food": {"topic": "food and healthy eating",
             "icons": ["teacup", "bowl", "chili", "coconut", "leaf", "drop", "cart", "heart", "palm_tree"]},
    "health_education": {"topic": "healthcare",
                         "icons": ["medical_cross", "pill", "heart", "user", "shield", "calendar", "book",
                                   "graduation_cap", "lightbulb", "document", "clock", "search"]},
}
