import pytest

from splitgraph.commands import push
from splitgraph.commands.publish import publish
from splitgraph.meta_handler.tags import get_current_head, get_tagged_id, set_tag
from splitgraph.registry_meta_handler import get_published_info
from splitgraph.sgfile import execute_commands
from test.splitgraph.conftest import REMOTE_CONN_STRING, OUTPUT, PG_MNT
from test.splitgraph.sgfile.test_execution import _add_multitag_dataset_to_remote_driver, _load_sgfile


@pytest.mark.parametrize('extra_info', [True, False])
def test_publish(empty_pg_conn, remote_driver_conn, extra_info):
    # Run some sgfile commands to create a dataset and push it
    new_head = _add_multitag_dataset_to_remote_driver(remote_driver_conn)
    execute_commands(empty_pg_conn, _load_sgfile('import_remote_multiple.sgfile'), params={'TAG': 'v1'},
                     output=OUTPUT)
    set_tag(empty_pg_conn, OUTPUT, get_current_head(empty_pg_conn, OUTPUT), 'v1')
    push(empty_pg_conn, OUTPUT, remote_conn_string=REMOTE_CONN_STRING)
    publish(empty_pg_conn, OUTPUT, 'v1', readme="A test repo.",
            include_provenance=extra_info, include_table_previews=extra_info)

    # Base the derivation on v2 of test/pg_mount and publish that too.
    execute_commands(empty_pg_conn, _load_sgfile('import_remote_multiple.sgfile'), params={'TAG': 'v2'},
                     output=OUTPUT)
    set_tag(empty_pg_conn, OUTPUT, get_current_head(empty_pg_conn, OUTPUT), 'v2')
    push(empty_pg_conn, OUTPUT, remote_conn_string=REMOTE_CONN_STRING)
    publish(empty_pg_conn, OUTPUT, 'v2', readme="Based on v2.",
            include_provenance=extra_info, include_table_previews=extra_info)

    image_hash, published_dt, provenance, readme, schemata, previews = get_published_info(remote_driver_conn, OUTPUT, 'v1')
    assert image_hash == get_tagged_id(empty_pg_conn, OUTPUT, 'v1')
    assert readme == "A test repo."
    expected_schemata = {'join_table': [['id', 'integer', False],
                                        ['fruit', 'character varying', False],
                                        ['vegetable', 'character varying', False]],
                         'my_fruits': [['fruit_id', 'integer', False],
                                       ['name', 'character varying', False]],
                         'vegetables': [['vegetable_id', 'integer', False],
                                        ['name', 'character varying', False]]}

    assert schemata == expected_schemata
    if extra_info:
        assert provenance == [[['test', 'pg_mount'], get_tagged_id(remote_driver_conn, PG_MNT, 'v1')]]
        assert previews == {'join_table': [[1, 'apple', 'potato'], [2, 'orange', 'carrot']],
                            'my_fruits': [[1, 'apple'], [2, 'orange']],
                            'vegetables': [[1, 'potato'], [2, 'carrot']]}

    else:
        assert provenance is None
        assert previews is None

    image_hash, published_dt, provenance, readme, schemata, previews = get_published_info(remote_driver_conn, OUTPUT, 'v2')
    assert image_hash == get_tagged_id(empty_pg_conn, OUTPUT, 'v2')
    assert readme == "Based on v2."
    assert schemata == expected_schemata
    if extra_info:
        assert provenance == [[['test', 'pg_mount'], get_tagged_id(remote_driver_conn, PG_MNT, 'v2')]]
        assert previews == {'join_table': [[2, 'orange', 'carrot']],
                            'my_fruits': [[2, 'orange']],
                            'vegetables': [[1, 'potato'], [2, 'carrot']]}
    else:
        assert provenance is None
        assert previews is None
