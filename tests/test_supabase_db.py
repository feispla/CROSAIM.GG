import supabase_db


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, response):
        self.response = response
        self.filters = []
        self.inserted = None
        self.updated = None

    def select(self, _columns):
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def update(self, row):
        self.updated = row
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, _value):
        return self

    def execute(self):
        return self.response


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.queries = []

    def table(self, _name):
        query = FakeQuery(next(self.responses))
        self.queries.append(query)
        return query


def test_save_submission_maps_fields_and_returns_id(monkeypatch):
    fake = FakeClient([FakeResponse([{"id": "submission-123"}])])
    monkeypatch.setattr(supabase_db, "_client", fake)

    submission_id = supabase_db.save_submission(
        {"name": "Ana", "role": "Duelista", "rank": "Diamante", "texto": "Hola"},
        webhook_message_id=456,
        webhook_id=789,
    )

    assert submission_id == "submission-123"
    row = fake.queries[0].inserted
    assert row["nombre"] == "Ana"
    assert row["rol"] == "Duelista"
    assert row["rango"] == "Diamante"
    assert row["discord_postulacion_message_id"] == "456"
    assert row["discord_webhook_id"] == "789"
    assert row["descripcion"] == "Hola"


def test_save_submission_raises_when_supabase_returns_no_row(monkeypatch):
    fake = FakeClient([FakeResponse([])])
    monkeypatch.setattr(supabase_db, "_client", fake)

    try:
        supabase_db.save_submission({"nombre": "Ana"})
    except RuntimeError as error:
        assert "no devolvió" in str(error)
    else:
        raise AssertionError("Expected RuntimeError")


def test_set_status_updates_review_metadata(monkeypatch):
    fake = FakeClient([FakeResponse([])])
    monkeypatch.setattr(supabase_db, "_client", fake)

    supabase_db.set_status("submission-123", "aprobada", 999, approval_message_id=111)

    query = fake.queries[0]
    assert ("id", "submission-123") in query.filters
    assert query.updated["estado"] == "aprobada"
    assert query.updated["revisado_por_discord_id"] == "999"
    assert query.updated["discord_aprobacion_message_id"] == "111"
    assert "reviewed_at" in query.updated
