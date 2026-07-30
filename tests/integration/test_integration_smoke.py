import pytest

from src.main import main


@pytest.mark.integration
def test_integration_smoke():
    main()
