"""Similar-assignment scoring. SimpleTestCase: the queryset is faked, no database."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from mls import views


def sub(pk, city="Vaughan", price="700000", project=None, builder="", purpose="assignment"):
    return SimpleNamespace(
        pk=pk, city=city, asking_price=Decimal(price) if price else None,
        precon_property_id=project, builder_name=builder, purpose=purpose,
    )


class FakeQS(list):
    def filter(self, **kwargs):
        return FakeQS(s for s in self if all(getattr(s, k) == v for k, v in kwargs.items()))

    def exclude(self, pk=None, **kwargs):
        rows = [s for s in self if s.pk != pk] if pk is not None else list(self)
        for key, value in kwargs.items():
            if key.endswith("__isnull"):
                field = key[: -len("__isnull")]
                # exclude(field__isnull=True) keeps non-null rows.
                if value:
                    rows = [s for s in rows if getattr(s, field, None) is not None]
                else:
                    rows = [s for s in rows if getattr(s, field, None) is None]
            elif key.endswith("__exact"):
                field = key[: -len("__exact")]
                rows = [s for s in rows if getattr(s, field, None) != value]
            else:
                rows = [s for s in rows if getattr(s, key, None) != value]
        return FakeQS(rows)

    def values_list(self, *fields, flat=False):
        if flat and len(fields) == 1:
            return FakeValues([getattr(s, fields[0]) for s in self])
        return FakeValues([tuple(getattr(s, f) for f in fields) for s in self])

    def distinct(self):
        return self

    def order_by(self, *args):
        return self


class FakeValues(list):
    def distinct(self):
        seen = []
        for item in self:
            if item not in seen:
                seen.append(item)
        return FakeValues(seen)

    def order_by(self, *args):
        return FakeValues(sorted(self, key=lambda value: str(value).lower()))


class SimilarTests(SimpleTestCase):
    def rank(self, subject, others):
        with mock.patch.object(views, "_public_submissions", return_value=FakeQS([subject, *others])):
            return [s.pk for s in views.similar_public_submissions(subject, limit=4)]

    def test_same_project_ranks_first(self):
        subject = sub(1, project=9)
        others = [sub(2, city="Vaughan"), sub(3, city="Toronto", project=9)]
        self.assertEqual(self.rank(subject, others)[0], 3)

    def test_excludes_self_other_purposes_and_unrelated(self):
        subject = sub(1)
        others = [sub(2, purpose="sale"), sub(3, city="Ottawa", price=None), sub(4)]
        self.assertEqual(self.rank(subject, others), [4])

    def test_closer_price_wins_within_a_city(self):
        subject = sub(1, price="700000")
        others = [sub(2, price="1400000"), sub(3, price="710000")]
        self.assertEqual(self.rank(subject, others), [3, 2])


class AvailableCitiesTests(SimpleTestCase):
    def test_dedupes_and_sorts_case_insensitively(self):
        qs = FakeQS(
            [
                sub(1, city="Toronto"),
                sub(2, city="vaughan"),
                sub(3, city="Toronto"),
                sub(4, city="  "),
                sub(5, city="Mississauga"),
            ]
        )
        self.assertEqual(
            views._available_cities(qs),
            ["Mississauga", "Toronto", "vaughan"],
        )


class HomeTypeFilterTests(SimpleTestCase):
    def test_values_or_together_and_unknowns_are_ignored(self):
        from django.http import QueryDict

        from mls.services.query_helpers import home_type_q

        self.assertIsNone(home_type_q(QueryDict("home_type=castle")))
        self.assertIsNone(home_type_q(QueryDict("")))
        combined = home_type_q(QueryDict("home_type=condo,townhouse"))
        self.assertIn("Apartment", str(combined))
        self.assertIn("Row / Townhouse", str(combined))
        detached = str(home_type_q(QueryDict("home_type=detached")))
        self.assertIn("property_attached_yn", detached)
        semi = str(home_type_q(QueryDict("home_type=semi")))
        self.assertIn("Semi-Detached", semi)
        condo = str(home_type_q(QueryDict("home_type=condo")))
        self.assertIn("Condo Apartment", condo)
