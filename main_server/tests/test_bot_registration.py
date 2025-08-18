"""
Test bot registration using shared fixtures from conftest.py.
"""

import pytest

# Bot registration endpoint
BOT_REGISTRATION_ENDPOINT = "/bots/register"


# pytest -s tests/test_bot_registration.py::test_bot_registration_success
def test_bot_registration_success(client_with_db):
    """Test successful bot registration."""
    
    client, mock_conn = client_with_db
    
    # Arrange
    bot_id = "test-bot-001"
    expected_response = {"status": "registered", "bot_id": bot_id}
    
    print(f"\n--- BOT REGISTRATION REQUEST ---")
    print(f"Endpoint: {BOT_REGISTRATION_ENDPOINT}")
    print(f"Bot ID: {bot_id}")
    print(f"Expected Response: {expected_response}")
    
    # Act - Send registration request
    response = client.post(BOT_REGISTRATION_ENDPOINT, json={"bot_id": bot_id})
    
    print(f"\n--- BOT REGISTRATION RESPONSE ---")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    # Assert HTTP response
    assert response.status_code == 200
    assert response.json() == expected_response
    
    # Verify database execute was called with correct query
    print(f"\n--- DATABASE VERIFICATION ---")
    mock_conn.execute.assert_called()
    call_args = mock_conn.execute.call_args[0]
    query = call_args[0]
    bot_id_param = call_args[1]
    
    print(f"Database query executed: {query[:50]}...")
    print(f"Bot ID parameter: {bot_id_param}")
    
    assert "INSERT INTO bots" in query
    assert bot_id_param == bot_id
    
    print("Bot registration test passed!")
    print("--- END TEST ---")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
