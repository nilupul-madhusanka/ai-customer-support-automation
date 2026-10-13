from streamlit.testing.v1 import AppTest

from services.config import ROOT
from services.storage import CsvRepository


def test_dashboard_process_edit_approve_and_filter(tmp_path, monkeypatch):
    repository = CsvRepository(tmp_path / "ui.csv")
    repository.write(CsvRepository(ROOT / "data/sample_inquiries.csv").load())
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr("services.storage.get_repository", lambda **kwargs: repository)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert all(row["status"] == "DRAFTED" for row in repository.load())
    app.text_area[0].set_value("A response edited by the reviewer.")
    next(button for button in app.button if button.label == "Approve reviewed reply").click().run()
    assert not app.exception
    assert repository.load()[0]["final_reply"] == "A response edited by the reviewer."
    app.selectbox[0].select("APPROVED").run()
    assert not app.exception
    assert app.success[0].value == "Reviewed and approved"
