from unittest.mock import MagicMock, patch

from app.initial_data import init


def test_init_creates_core_data_and_seeds_program_catalog() -> None:
    session = MagicMock()
    session.__enter__.return_value = session

    with (
        patch("app.initial_data.Session", return_value=session),
        patch("app.initial_data.init_db") as init_db,
        patch("app.initial_data.seed_program_catalog") as seed_program_catalog,
    ):
        init()

    init_db.assert_called_once_with(session)
    seed_program_catalog.assert_called_once_with(session=session)
