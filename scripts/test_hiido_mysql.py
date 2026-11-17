"""Interactive read-only MySQL probe. Password stays in process memory."""
import getpass
import argparse
import json
import re
from pathlib import Path
import pymysql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='10.130.87.26')
    parser.add_argument('--port', type=int, default=10130)
    parser.add_argument('--user', default='sodadev_o')
    parser.add_argument('--database')
    parser.add_argument('--table', default='dws_marki_bill_detail_bd_quarter_da')
    parser.add_argument('--result', default='mysql-probe-result.json', choices=['mysql-probe-result.json','mysql-property-probe-result.json'])
    args = parser.parse_args()
    print('MySQL connection test')
    print(f'Host {args.host}:{args.port} | User {args.user} | Table {args.table}')
    print('Password input is hidden. No password is saved.')
    password = getpass.getpass('MySQL password: ')
    result = {'host': args.host, 'port': args.port,
              'table': args.table, 'ok': False}
    connection = None
    try:
        connection = pymysql.connect(host=result['host'], port=result['port'],
            user=args.user, password=password, database=args.database, connect_timeout=8,
            read_timeout=15, write_timeout=8, autocommit=False)
        password = None
        with connection.cursor() as cursor:
            if args.database:
                schemas = [args.database]
            else:
                cursor.execute('SELECT TABLE_SCHEMA FROM information_schema.TABLES WHERE TABLE_NAME=%s', (result['table'],))
                schemas = [row[0] for row in cursor.fetchall()]
            if not schemas:
                schema = input('Table not visible in metadata. Enter database/schema name: ').strip()
                schemas = [schema] if schema else []
            if not schemas:
                raise ValueError('No database/schema found or provided')
            if len(schemas) > 1:
                print('Matching schemas:', ', '.join(schemas))
                schema = input('Choose database/schema: ').strip()
                if schema not in schemas:
                    raise ValueError('Selected schema is not in matching schemas')
            else:
                schema = schemas[0]
            quoted_schema = '`' + schema.replace('`', '``') + '`'
            quoted_table = '`' + args.table.replace('`', '``') + '`'
            cursor.execute(f'SELECT * FROM {quoted_schema}.{quoted_table} LIMIT 0')
            result.update(ok=True, database=schema, columns=[column[0] for column in cursor.description])
            print('PASS: authenticated and target table SELECT permission verified.')
            print('Database/schema:', schema)
            print('Columns:', ', '.join(result['columns']))
            if args.table == 'dws_marki_bill_detail_bd_quarter_buss_da':
                cursor.execute(f'SELECT * FROM {quoted_schema}.{quoted_table} LIMIT 5000')
                columns = [column[0] for column in cursor.description]
                records = [dict(zip(columns, row)) for row in cursor.fetchall()]
                sample_path = Path(__file__).resolve().parent.parent / 'data/mysql-buss-inspection.json'
                sample_path.write_text(json.dumps({'database':schema,'table':args.table,
                    'limit':5000,'rows':records},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
                result['inspection_rows']=len(records)
                print('Read-only inspection rows:',len(records))
                print('Inspection saved:',sample_path)
    except pymysql.MySQLError as exc:
        code = exc.args[0] if exc.args else None
        result.update(error_code=code, error='MySQL connection or table read test failed')
        print('FAIL. MySQL error code:', code)
        if code == 1045:
            detail = str(exc.args[1]) if len(exc.args) > 1 else ''
            match = re.search(r"Access denied for user '([^']*)'@'([^']*)'", detail)
            if match:
                result['rejected_user'] = match.group(1)
                result['client_host_seen_by_mysql'] = match.group(2)
                print('Rejected account:', match.group(1))
                print('Client address seen by MySQL:', match.group(2))
            result['password_supplied'] = 'using password: YES' in detail
            print('Password supplied:', result['password_supplied'])
            print('If another SQL tool connects successfully, compare VPN, SSH tunnel, SSL and account settings.')
        print({1045:'Check password/account and allowed client IP.',1044:'Database access denied.',1142:'Table SELECT denied.',1146:'Table not found.',2003:'Network connection failed.',2026:'TLS negotiation failed.'}.get(code,'Check network, authentication, TLS and table permissions.'))
    except Exception as exc:
        result['error'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print('FAIL:', result['error'])
    finally:
        password = None
        if connection:
            connection.close()
        destination = Path(__file__).resolve().parent.parent / 'data' / args.result
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Result saved:', destination)


if __name__ == '__main__':
    main()
