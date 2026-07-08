"""Baked-in sample applications so a reviewer can try the app in one click.

Every sample references a label image in app/static/samples/. If you add or
remove images there, update this file to match.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ApplicationRecord, BeverageClass


@dataclass
class Sample:
    id: str
    title: str
    subtitle: str
    image_path: str  # relative to app/static/
    application: ApplicationRecord


SAMPLES: list[Sample] = [
    Sample(
        id="bourbon-clean",
        title="Old Tom Distillery",
        subtitle="Kentucky Straight Bourbon — everything matches",
        image_path="samples/bourbon-clean.png",
        application=ApplicationRecord(
            brand_name="Old Tom Distillery",
            class_type="Kentucky Straight Bourbon Whiskey",
            alcohol_content="45% Alc./Vol. (90 Proof)",
            alcohol_pct=45.0,
            net_contents="750 mL",
            bottler_name="Old Tom Distillery Co.",
            bottler_address="Bardstown, KY",
            beverage_class=BeverageClass.SPIRITS,
        ),
    ),
    Sample(
        id="stones-throw",
        title="Stone's Throw Brewing",
        subtitle="Dave's case — label reads STONE'S THROW, application reads Stone's Throw",
        image_path="samples/stones-throw.png",
        application=ApplicationRecord(
            brand_name="Stone's Throw",
            class_type="India Pale Ale",
            alcohol_content="6.8% Alc./Vol.",
            alcohol_pct=6.8,
            net_contents="12 fl oz",
            bottler_name="Stone's Throw Brewing LLC",
            bottler_address="Bend, OR",
            beverage_class=BeverageClass.BEER,
        ),
    ),
    Sample(
        id="wine-warning-issue",
        title="Riverbend Cellars",
        subtitle="Warning statement uses title case — should fail",
        image_path="samples/riverbend-cellars.png",
        application=ApplicationRecord(
            brand_name="Riverbend Cellars",
            class_type="Willamette Valley Pinot Noir",
            alcohol_content="13.5% Alc./Vol.",
            alcohol_pct=13.5,
            net_contents="750 mL",
            bottler_name="Riverbend Cellars",
            bottler_address="Newberg, OR",
            beverage_class=BeverageClass.WINE,
        ),
    ),
    Sample(
        id="abv-mismatch",
        title="Northgate Rye",
        subtitle="Label says 47%, application says 45% — over tolerance",
        image_path="samples/northgate-rye.png",
        application=ApplicationRecord(
            brand_name="Northgate Rye",
            class_type="Straight Rye Whiskey",
            alcohol_content="45% Alc./Vol.",
            alcohol_pct=45.0,
            net_contents="750 mL",
            bottler_name="Northgate Distilling Co.",
            bottler_address="Portland, OR",
            beverage_class=BeverageClass.SPIRITS,
        ),
    ),
]


def by_id(sample_id: str) -> Sample | None:
    for s in SAMPLES:
        if s.id == sample_id:
            return s
    return None
