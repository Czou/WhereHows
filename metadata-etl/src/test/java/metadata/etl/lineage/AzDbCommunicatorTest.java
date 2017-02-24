/**
 * Copyright 2015 LinkedIn Corp. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 */
package metadata.etl.lineage;

import java.io.IOException;
import java.sql.SQLException;
import java.util.Properties;
import org.testng.Assert;
import org.testng.annotations.BeforeTest;
import org.testng.annotations.Test;


/**
 * Created by zsun on 9/21/15.
 */
@Test(groups = {"needConfig"})
public class AzDbCommunicatorTest {
  AzDbCommunicator adc;

  @BeforeTest
  public void setUp()
    throws Exception {
    Properties prop = new LineageTest().properties;
    adc = new AzDbCommunicator(prop);
  }

  public void getExecLogTest()
    throws IOException, SQLException {
    int execId = 870536;
    String jobName = "azkaban-log_load-azkaban-log";
    String log = adc.getExecLog(execId, jobName);
    Assert.assertNotNull(log);
  }
}
