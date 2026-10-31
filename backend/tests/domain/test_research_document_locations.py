import pytest

@pytest.fixture(autouse=True)
def postgres_schema():yield None

def test_page_locator_uses_parsed_item_location_and_rejects_absent_page():
    from app.domain.research_results.sources import document_page_items
    items=[{'id':'a','location':{'page_number':1},'text':'first'},{'id':'b','location':{'page_number':2},'text':'second'}]
    assert document_page_items(items,2)==[items[1]]
    with pytest.raises(Exception) as exc:document_page_items(items,3)
    assert exc.value.code=='research_locator_invalid'
