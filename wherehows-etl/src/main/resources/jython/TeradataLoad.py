#
# Copyright 2015 LinkedIn Corp. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#

import datetime
import os
import sys

from com.ziclix.python.sql import zxJDBC
from distutils.util import strtobool
from wherehows.common import Constant
from org.slf4j import LoggerFactory

import FileUtil


class TeradataLoad:
  def __init__(self):
    self.logger = LoggerFactory.getLogger('jython script : ' + self.__class__.__name__)

  def load_metadata(self):
    load_cmd = '''
        DELETE FROM stg_dict_dataset WHERE db_id = {db_id};

        LOAD DATA LOCAL INFILE '{source_file}'
        INTO TABLE stg_dict_dataset
        FIELDS TERMINATED BY '\Z' ESCAPED BY '\0'
        (`name`, `schema`, properties, fields, urn, source, sample_partition_full_path, source_created_time, source_modified_time)
        SET db_id = {db_id},
            storage_type = 'Table',
            is_active = TRUE,
            wh_etl_exec_id = {wh_etl_exec_id};

        -- SELECT COUNT(*) FROM stg_dict_dataset;
        -- clear
        DELETE FROM stg_dict_dataset where db_id = {db_id}
          AND (length(`name`) = 0
           OR `name` like 'tmp\_%'
           OR `name` like '%\_tmp'
           OR `name` like '#%'
           OR `name` regexp '^LS_[[:alnum:]_]+_[[:digit:]]')
        ;

        update stg_dict_dataset
        set location_prefix = substring_index(substring_index(urn, '/', 4), '/', -2) /* teradata location_prefix is it's schema name*/
        WHERE db_id = {db_id} and location_prefix is null;

        update stg_dict_dataset
        set parent_name = substring_index(substring_index(urn, '/', 4), '/', -1) /* teradata parent_name is it's schema name*/
        where db_id = {db_id} and parent_name is null;

        -- load into stg_dict_dataset_instance
        DELETE FROM stg_dict_dataset_instance WHERE db_id = {db_id};
        INSERT INTO stg_dict_dataset_instance
        ( dataset_urn,
          db_id,
          deployment_tier,
          data_center,
          server_cluster,
          slice,
          is_active,
          native_name,
          logical_name,
          `version`,
          instance_created_time,
          created_time,
          wh_etl_exec_id,
          abstract_dataset_urn,
          schema_text
        )
        select s.urn, {db_id}, d.deployment_tier, d.data_center, d.cluster,
          '*', s.is_active, s.name, s.name, 0, s.source_created_time, s.created_time,
           {wh_etl_exec_id}, s.urn, s.schema
        from stg_dict_dataset s JOIN cfg_database d on s.db_id = d.db_id
        where s.db_id = {db_id}
        on duplicate key update
          deployment_tier=d.deployment_tier, data_center=d.data_center,
          server_cluster=d.cluster, is_active=s.is_active, native_name=s.name, logical_name=s.name,
          instance_created_time=s.source_created_time, created_time=s.created_time,
          wh_etl_exec_id={wh_etl_exec_id}, abstract_dataset_urn=s.urn, schema_text=s.schema;

        -- insert into final table
        INSERT INTO dict_dataset
        ( `name`,
          `schema`,
          schema_type,
          fields,
          properties,
          urn,
          source,
          location_prefix,
          parent_name,
          storage_type,
          ref_dataset_id,
          is_active,
          dataset_type,
          hive_serdes_class,
          is_partitioned,
          partition_layout_pattern_id,
          sample_partition_full_path,
          source_created_time,
          source_modified_time,
          created_time,
          wh_etl_exec_id
        )
        select s.name, s.schema, s.schema_type, s.fields,
          s.properties, s.urn,
          s.source, s.location_prefix, s.parent_name,
          s.storage_type, s.ref_dataset_id, s.is_active,
          s.dataset_type, s.hive_serdes_class, s.is_partitioned,
          s.partition_layout_pattern_id, s.sample_partition_full_path,
          s.source_created_time, s.source_modified_time, UNIX_TIMESTAMP(now()),
          s.wh_etl_exec_id
        from stg_dict_dataset s
        where s.db_id = {db_id}
        on duplicate key update
          `name`=s.name, `schema`=s.schema, schema_type=s.schema_type, fields=s.fields,
          properties=s.properties, source=s.source, location_prefix=s.location_prefix, parent_name=s.parent_name,
          storage_type=s.storage_type, ref_dataset_id=s.ref_dataset_id, is_active=s.is_active,
          dataset_type=s.dataset_type, hive_serdes_class=s.hive_serdes_class, is_partitioned=s.is_partitioned,
          partition_layout_pattern_id=s.partition_layout_pattern_id, sample_partition_full_path=s.sample_partition_full_path,
          source_created_time=s.source_created_time, source_modified_time=s.source_modified_time,
          modified_time=UNIX_TIMESTAMP(now()), wh_etl_exec_id=s.wh_etl_exec_id
        ;
        analyze table dict_dataset;

        -- update dataset_id of instance table
        update stg_dict_dataset_instance sdi, dict_dataset d
        set sdi.dataset_id = d.id where sdi.abstract_dataset_urn = d.urn
        and sdi.db_id = {db_id};

        -- insert into final instance table
        INSERT INTO dict_dataset_instance
        ( dataset_id,
          db_id,
          deployment_tier,
          data_center,
          server_cluster,
          slice,
          is_active,
          native_name,
          logical_name,
          version,
          version_sort_id,
          schema_text,
          ddl_text,
          instance_created_time,
          created_time,
          wh_etl_exec_id
        )
        select s.dataset_id, s.db_id, s.deployment_tier, s.data_center,
          s.server_cluster, s.slice, s.is_active, s.native_name, s.logical_name, s.version,
          case when s.version regexp '[0-9]+\.[0-9]+\.[0-9]+'
            then cast(substring_index(s.version, '.', 1) as unsigned) * 100000000 +
                 cast(substring_index(substring_index(s.version, '.', 2), '.', -1) as unsigned) * 10000 +
                 cast(substring_index(s.version, '.', -1) as unsigned)
          else 0
          end version_sort_id, s.schema_text, s.ddl_text,
          s.instance_created_time, s.created_time, s.wh_etl_exec_id
        from stg_dict_dataset_instance s
        where s.db_id = {db_id}
        on duplicate key update
          deployment_tier=s.deployment_tier, data_center=s.data_center, server_cluster=s.server_cluster, slice=s.slice,
          is_active=s.is_active, native_name=s.native_name, logical_name=s.logical_name, version=s.version,
          schema_text=s.schema_text, ddl_text=s.ddl_text,
          instance_created_time=s.instance_created_time, created_time=s.created_time, wh_etl_exec_id=s.wh_etl_exec_id
          ;
        '''.format(source_file=self.input_file, db_id=self.db_id, wh_etl_exec_id=self.wh_etl_exec_id)

    self.executeCommands(load_cmd)
    self.logger.info("Finish loading metadata")


  def load_field(self):
    load_cmd = '''
        DELETE FROM stg_dict_field_detail where db_id = {db_id};

        LOAD DATA LOCAL INFILE '{source_file}'
        INTO TABLE stg_dict_field_detail
        FIELDS TERMINATED BY '\Z'
        (urn, sort_id, parent_sort_id, parent_path, field_name, field_label, data_type,
         data_size, @precision, @scale, is_nullable,
         is_indexed, is_partitioned, default_value, namespace, description,
         @dummy
        )
        set
          data_precision=nullif(@precision,''),
          data_scale=nullif(@scale,''),
          db_id = {db_id};

        analyze table stg_dict_field_detail;

        update stg_dict_field_detail
        set description = null
        where db_id = {db_id}
           and (char_length(trim(description)) = 0
           or description in ('null', 'N/A', 'nothing', 'empty', 'none'));

        -- update stg_dict_field_detail dataset_id
        update stg_dict_field_detail sf, dict_dataset d
        set sf.dataset_id = d.id where sf.urn = d.urn
        and sf.db_id = {db_id};
        delete from stg_dict_field_detail
        where db_id = {db_id} and dataset_id is null;  -- remove if not match to dataset

        -- delete old record if it does not exist in this load batch anymore (but have the dataset id)
        create temporary table if not exists t_deleted_fields (primary key (field_id)) ENGINE=MyISAM
          SELECT x.field_id
          FROM (select dataset_id, field_name, parent_path from stg_dict_field_detail where db_id = {db_id}) s
          RIGHT JOIN
            ( select dataset_id, field_id, field_name, parent_path from dict_field_detail
              where dataset_id in (select dataset_id from stg_dict_field_detail where db_id = {db_id})
            ) x
            ON s.dataset_id = x.dataset_id
            AND s.field_name = x.field_name
            AND s.parent_path <=> x.parent_path
          WHERE s.field_name is null
        ; -- run time : ~2min

        delete from dict_field_detail where field_id in (select field_id from t_deleted_fields);

        -- update the old record if some thing changed
        update dict_field_detail t join
        (
          select x.field_id, s.*
          from stg_dict_field_detail s
               join dict_field_detail x
            on s.dataset_id = x.dataset_id
            and s.field_name = x.field_name
            and s.parent_path <=> x.parent_path
          where s.db_id = {db_id}
            and (x.sort_id <> s.sort_id
                or x.parent_sort_id <> s.parent_sort_id
                or x.data_type <> s.data_type
                or x.data_size <> s.data_size or (x.data_size is null XOR s.data_size is null)
                or x.data_precision <> s.data_precision or (x.data_precision is null XOR s.data_precision is null)
                or x.is_nullable <> s.is_nullable or (x.is_nullable is null XOR s.is_nullable is null)
                or x.is_partitioned <> s.is_partitioned or (x.is_partitioned is null XOR s.is_partitioned is null)
                or x.is_distributed <> s.is_distributed or (x.is_distributed is null XOR s.is_distributed is null)
                or x.default_value <> s.default_value or (x.default_value is null XOR s.default_value is null)
                or x.namespace <> s.namespace or (x.namespace is null XOR s.namespace is null)
            )
        ) p
          on t.field_id = p.field_id
        set t.sort_id = p.sort_id,
            t.parent_sort_id = p.parent_sort_id,
            t.data_type = p.data_type,
            t.data_size = p.data_size,
            t.data_precision = p.data_precision,
            t.is_nullable = p.is_nullable,
            t.is_partitioned = p.is_partitioned,
            t.is_distributed = p.is_distributed,
            t.default_value = p.default_value,
            t.namespace = p.namespace,
            t.modified = now()
        ;

        show warnings limit 10;

        insert into dict_field_detail (
        dataset_id, fields_layout_id, sort_id, parent_sort_id,
        field_name, data_type, data_size, data_precision, data_fraction,
        is_nullable, /* is_indexed, is_partitioned, is_distributed, */
        modified
        )
        select
          s.dataset_id,
          0 as fields_layout_id,
          s.sort_id,
          0 parent_sort_id,
          s.field_name,
          s.data_type,
          s.data_size,
          s.data_precision,
          s.data_scale,
          s.is_nullable,
          now()
        from stg_dict_field_detail s
             left join dict_field_detail f
          on s.dataset_id = f.dataset_id
         and s.field_name = f.field_name
        where db_id = {db_id} and f.field_id is null;

        analyze table dict_field_detail;

        -- delete old record in staging field comment map
        delete from stg_dict_dataset_field_comment where db_id = {db_id};

        -- insert new field comments
        insert into field_comments (
          user_id, comment, created, modified, comment_crc32_checksum
        )
        select 0 user_id, description, now() created, now() modified, crc32(description) from
        (
          select sf.description
          from stg_dict_field_detail sf left join field_comments fc
            on sf.description = fc.comment
          where sf.description is not null
            and fc.id is null
            and sf.db_id = {db_id}
          group by 1 order by 1
        ) d;

        analyze table field_comments;

        -- insert field to comment map to staging
        insert ignore into stg_dict_dataset_field_comment
        select t.field_id field_id, fc.id comment_id, sf.dataset_id, {db_id}
                from stg_dict_field_detail sf
                      join field_comments fc
                  on sf.description = fc.comment
                      join dict_field_detail t
                  on sf.dataset_id = t.dataset_id
                  and sf.field_name = t.field_name
                  and sf.parent_path <=> t.parent_path
        where sf.db_id = {db_id};

        -- have default comment, insert it set default to 0
        insert ignore into dict_dataset_field_comment
        select field_id, comment_id, dataset_id, 0 is_default from stg_dict_dataset_field_comment where field_id in (
          select field_id from dict_dataset_field_comment
          where field_id in (select field_id from stg_dict_dataset_field_comment)
        and is_default = 1 ) and db_id = {db_id};

        -- doesn't have this comment before, insert into it and set as default
        insert ignore into dict_dataset_field_comment
        select sd.field_id, sd.comment_id, sd.dataset_id, 1 from stg_dict_dataset_field_comment sd
        left join dict_dataset_field_comment d
        on d.field_id = sd.field_id
         and d.comment_id = sd.comment_id
        where d.comment_id is null
        and sd.db_id = {db_id};
        '''.format(source_file=self.input_field_file, db_id=self.db_id)

    self.executeCommands(load_cmd)
    self.logger.info("Finish loading fields ")


  def load_sample(self):
    load_cmd = '''
    DELETE FROM stg_dict_dataset_sample WHERE db_id = {db_id};

    LOAD DATA LOCAL INFILE '{source_file}'
    INTO TABLE stg_dict_dataset_sample FIELDS TERMINATED BY '\Z' ESCAPED BY '\0'
    (urn,ref_urn,data)
    SET db_id = {db_id};

    -- update dataset id in staging table
    UPDATE stg_dict_dataset_sample s
    JOIN dict_dataset d ON s.db_id = {db_id} and s.urn = d.urn
    SET s.dataset_id = d.id;

    -- update reference id in staging table
    UPDATE stg_dict_dataset_sample s
    JOIN (
      select dataset_id, id from
      (select dataset_id, ref_urn from stg_dict_dataset_sample
      where db_id = 3 and ref_urn > '') st
      join dict_dataset on urn = ref_urn) d
    ON s.dataset_id = d.dataset_id
    SET s.ref_id = d.id;

    -- first insert ref_id as 0
    INSERT INTO dict_dataset_sample
    ( `dataset_id`,
      `urn`,
      `ref_id`,
      `data`,
      created
    )
    SELECT * from
      (select dataset_id, urn, ref_id s_ref_id, `data` s_data, now()
      from stg_dict_dataset_sample WHERE db_id = {db_id}) s
    ON DUPLICATE KEY UPDATE
      ref_id = COALESCE(s_ref_id, ref_id),
      `data`=s_data,
      modified=now();
    '''.format(source_file=self.input_sampledata_file, db_id=self.db_id)

    self.executeCommands(load_cmd)
    self.logger.info("Finish loading samples ")


  def executeCommands(self, commands):
    for cmd in commands.split(";"):
      self.logger.debug(cmd)
      self.conn_cursor.execute(cmd)
      self.conn_mysql.commit()


if __name__ == "__main__":
  args = sys.argv[1]

  l = TeradataLoad()

  # set up connection
  username = args[Constant.WH_DB_USERNAME_KEY]
  password = args[Constant.WH_DB_PASSWORD_KEY]
  JDBC_DRIVER = args[Constant.WH_DB_DRIVER_KEY]
  JDBC_URL = args[Constant.WH_DB_URL_KEY]

  temp_dir = FileUtil.etl_temp_dir(args, "TERADATA")
  l.input_file = os.path.join(temp_dir, args[Constant.TD_METADATA_KEY])
  l.input_field_file = os.path.join(temp_dir, args[Constant.TD_FIELD_METADATA_KEY])
  l.input_sampledata_file = os.path.join(temp_dir, args[Constant.TD_SAMPLE_OUTPUT_KEY])

  do_sample = False
  if Constant.TD_LOAD_SAMPLE in args:
    do_sample = strtobool(args[Constant.TD_LOAD_SAMPLE])

  if datetime.datetime.now().strftime('%a') not in args[Constant.TD_COLLECT_SAMPLE_DATA_DAYS]:
    do_sample = False

  l.db_id = args[Constant.DB_ID_KEY]
  l.wh_etl_exec_id = args[Constant.WH_EXEC_ID_KEY]
  l.conn_mysql = zxJDBC.connect(JDBC_URL, username, password, JDBC_DRIVER)
  l.conn_cursor = l.conn_mysql.cursor()

  if Constant.INNODB_LOCK_WAIT_TIMEOUT in args:
    lock_wait_time = args[Constant.INNODB_LOCK_WAIT_TIMEOUT]
    l.conn_cursor.execute("SET innodb_lock_wait_timeout = %s;" % lock_wait_time)

  try:
    l.load_metadata()
    l.load_field()
    if do_sample:
      l.load_sample()
  finally:
    l.conn_mysql.close()
