def test_postgres(postgres):
    assert postgres.is_started()
