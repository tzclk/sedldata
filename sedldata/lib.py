import datetime
import html
import json
import os
import getpass

import alembic.config
import jinja2
from flattentool import unflatten

from sedldata.database import Database


def in_notebook():
    if 'JPY_PARENT_PID' in os.environ:
        return True
    return False


def xl_to_json(infile, outfile):
    try:
        unflatten(
                input_name=infile,
                output_name=outfile,
                input_format='xlsx',
                metatab_name='Meta',
                metatab_vertical_orientation=True,
                root_list_path='deals',
                id_name='id',
                cell_source_map='sourcemap-' + outfile,
                root_id='')
        with open(outfile,'r') as json_file:
            data = json.load(json_file)
        with open('sourcemap-' + outfile,'r') as source_map:
            source_map_data = json.load(source_map)
    except Exception as e:
        raise e

    return data, source_map_data

table = jinja2.Template(
'''
<table class="dataframe">
    <thead>
    <tr>
      {% for header in headers %}
        <th style="text-align: left; vertical-align: top">{{ header }}</th>
      {% endfor %}
    </tr>
    </thead>
    <tbody>
      {% for row in data %}
        <tr>
          {% for cell in row %}
              <td style="text-align: left; vertical-align: top">
                <pre>{{ cell|truncate(50) }}</pre>
              </td>
          {% endfor %}
        </tr>
      {% endfor %}
    </tbody>
</table>
'''
)


def generate_rows(result, limit):
    for num, row in enumerate(result):
        if num == limit:
            break
        yield [json.dumps(item, indent=2) if isinstance(item, dict) else html.escape(str(item)) for item in row]


class Session:

    def __init__(self, db_uri=None):
        if in_notebook():
            if not db_uri:
                db_uri = 'postgresql://sedldata:{password}@46.43.2.250:5432/sedldata'
            if '{password}' in db_uri:
                db_uri = db_uri.format(password=getpass.getpass("Enter database password:  "))
            self.db = Database(db_uri)
            self.db.upgrade()
        else:
            self.db = Database()


    def load_xlsx(self, collection=None, infile=None, outfile='output.json'):
        if not collection and in_notebook():
            collection = input('Please state collections name: ')
        if not collection:
            raise ValueError('You need to input a non-empty collection name!')

        if in_notebook():
            from google.colab import files
            print('Upload your xlsx SEDL file:')
            uploaded = files.upload()
            for file_name in uploaded:
                infile = 'uploaded.xlsx'
                with open(infile, '+wb') as f:
                    f.write(uploaded[file_name])
                break
        
        if not infile:
            raise ValueError('You need to state an input file')

        unflattened, source_map = xl_to_json(infile, outfile)
        deal_indexes = set()
        org_indexes = set()

        for path, value in source_map.items():
            split_path = path.split('/')
            if len(split_path) < 2:
                continue
            index = int(split_path[1])
            for source_item in value:
                if source_item[0].lower().strip().startswith('deal'):
                    deal_indexes.add(index)
                if source_item[0].lower().strip().startswith('org'):
                    org_indexes.add(index)

        metadata = {key: value for key, value in unflattened.items() if key != 'deals'}
        for num, obj in enumerate(unflattened['deals']):
            now = datetime.datetime.now()
            obj_id = obj.get('id')
            if not obj_id:
                print(num)
                print('WARNING: object {} has no id field'.format(obj))
                continue
            if num in deal_indexes:
                obj_id = obj.get('id')
                insert = self.db.deal_table.insert()
                insert.execute(date_loaded=now, collection=collection, deal=obj, deal_id=obj_id, metadata=metadata)
            if num in org_indexes:
                obj_id = obj['id']
                insert = self.db.org_table.insert()
                insert.execute(date_loaded=now, collection=collection, organization=obj, org_id=obj_id, metadata=metadata)

        now = datetime.datetime.now()
        print("Loaded %s at: %s" % (collection, now))


    def delete_collection(self, collection):
        self.run_sql('''delete from deal where collection = %s ''', params=[collection])
        self.run_sql('''delete from organization where collection = %s ''', params=[collection])

    def get_results(self, sql, limit=-1, params=None):

        with self.db.engine.begin() as connection:
            params = params or []
            sql_result = connection.execute(sql, *params)
            if sql_result.returns_rows:
                results = {
                    "data": [row for row in generate_rows(sql_result, limit)],
                    "headers": sql_result.keys()
                }
                return results
            else:
                return "Success"


    def run_sql(self, sql, limit=100, params=None):
        from IPython.core.display import display, HTML
        results = self.get_results(sql, limit, params)
        if results == 'Success':
            return results
        display(HTML(table.render(results)))
