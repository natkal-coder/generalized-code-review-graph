# Databricks notebook source
import os


def load_config():
    return {"env": os.getenv("ENV", "dev")}

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM bronze.events
# MAGIC JOIN silver.users ON events.user_id = users.id

# COMMAND ----------

# MAGIC %r
# MAGIC summarize_data <- function(df) {
# MAGIC   summary(df)
# MAGIC }

# COMMAND ----------

# MAGIC %md
# MAGIC ## Analysis Notes
# MAGIC This section documents the analysis.

# COMMAND ----------

def process_events(config):
    return load_config()

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE TABLE gold.summary AS SELECT * FROM silver.processed
