# Importing required function
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
import pyspark.sql.functions as F


# UDF1 to determine Is_Order in case of Order.
def udf1(a):
    if a == "ORDER":
        return(1)
    else:
        return(0)
		
# UDF2 to determine Is_Return in case of Return.
def udf2(a):
    if a == "RETURN":
        return(1) 
    else:
        return(0)
		
# UDF3 to determine Total Order Cost. 

def udf3(a,b,c):
    if a == "ORDER":
        return (b*c)
    else:
        return ((b*c) * -1)


# Establishing Spark Session
spark = SparkSession  \
	.builder  \
	.appName("StructuredSocketRead")  \
	.getOrCreate()
spark.sparkContext.setLogLevel('ERROR')	


# Reading data from Kafka Server & Topic given	
lines = spark  \
	.readStream  \
	.format("kafka")  \
	.option("kafka.bootstrap.servers","18.211.252.152:9092")  \
	.option("subscribe","real-time-project")  \
    .option("failOnDataLoss","false") \
    .option("startingOffsets", "earliest")  \
	.load()

# Defining Schema
schema =  StructType([
                StructField("country", StringType()),
                StructField("invoice_no", LongType()) ,
                StructField("items", ArrayType(
                    StructType([
                        StructField("SKU", StringType()),
                        StructField("title", StringType()),
                        StructField("unit_price", FloatType()),
                        StructField("quantity", IntegerType())
                              ])
                        )),
                StructField("timestamp", TimestampType()),
                StructField("type", StringType()),  
            ])

# Casting raw data as string and aliasing          
Casted = lines.select(from_json(col("value") \
                                    .cast("string") \
                                    ,schema).alias("parsed"))

# Parsed DF                                    
new_df = Casted.select("parsed.*")

# unveiling items array to derive new columns & KPIs
df1 = new_df.select(col("type"),col("country"),col("invoice_no"),col("timestamp"),explode(col("items")))

# Columns from Items array displayed
df2 = df1.select("type","country" , "invoice_no", "timestamp", "col.SKU","col.title","col.unit_price","col.quantity")

# Array Columns renamed 
df2 = df2.withColumnRenamed("col.SKU","SKU")
df2 = df2.withColumnRenamed("col.title","TITLE")
df2 = df2.withColumnRenamed("col.unit_price","unit_price")
df2 = df2.withColumnRenamed("col.quantity","quantity")

# Declare user def function for total cost
Cost_value = udf(udf3, FloatType())

# Adding Total Cost to data frame
df2 = df2.withColumn("Cost", Cost_value(df2.type,df2.unit_price, df2.quantity))


# Declare user def function Is Order
Det_Order = udf(udf1, IntegerType())

# Adding Is Order flag to existing DF
df2 = df2.withColumn("is_Order", Det_Order(df2.type))


# Declare user def function for Is Return
Det_Return = udf(udf2, IntegerType())

# Adding Is Return flag to existing DF
df2 = df2.withColumn("is_Return", Det_Return(df2.type))

# Selecting required cols Only
df2 = df2.select("invoice_no","country","timestamp","Cost","quantity","is_Order","is_Return")

# Pumping raw data to output the data for each order for window of 1 minute.
df3 = df2.withWatermark("timestamp","10 minutes") \
		 .groupby(window("timestamp","1 minute"),"invoice_no","country","is_Order","is_Return") \
         .sum("Cost","quantity")


#Time based KPI
df3_time = df2.select("invoice_no","timestamp","Cost","quantity","is_Order","is_Return")
Final_time = df3_time.withWatermark("timestamp", "10 minutes") \
			.groupby(window("timestamp","1 minute")) \
			.agg(sum("Cost").alias("Total_sales_vol"), \
			F.approx_count_distinct("invoice_no").alias("OPM"), \
			sum("is_Order").alias("total_Order"), \
			sum("is_Return").alias("total_return"), \
			sum("quantity").alias("total_items"))

#KPI for rate of return
Final_time = Final_time.withColumn("rate_of_return",Final_time.total_return/(Final_time.total_Order+Final_time.total_return))	
#KPI for average transaction size	
Final_time = Final_time.withColumn("Avg_trans_size",Final_time.Total_sales_vol/(Final_time.total_Order+Final_time.total_return))
Final_time = Final_time.select("window","OPM","Total_sales_vol","Avg_trans_size","rate_of_return")	

## Time and Country Based KPIs
df3_time_country = df2.select("country","invoice_no","timestamp","Cost","quantity","is_Order","is_Return")
Final = df3_time_country.withWatermark("timestamp", "10 minutes") \
			.groupby(window("timestamp","1 minute"),"country") \
			.agg(sum("Cost").alias("Total_sales_vol"), \
			F.approx_count_distinct("invoice_no").alias("OPM"), \
			sum("invoice_no").alias("sum_invoice"), \
			sum("is_Order").alias("total_Order"), \
			sum("is_Return").alias("total_return"), \
			sum("quantity").alias("total_items"))

#KPI for rate of return
Final = Final.withColumn("rate_of_return",Final.total_return/(Final.total_Order+Final.total_return))
Final_country_time = Final.select("window","country","OPM","Total_sales_vol","rate_of_return")	

#Printing Time KPI to HDFS as Json file
query_2 = Final_time.writeStream \
    .outputMode("Append") \
    .format("json") \
    .option("format","append") \
    .option("truncate", "false") \
    .option("path","time_KPI") \
    .option("checkpointLocation", "time_KPI_json") \
    .trigger(processingTime="1 minute") \
    .start()
    
# printing output on console      
query_1 = df3 \
	.writeStream  \
	.outputMode("complete")  \
	.format("console")  \
	.option("truncate", "False")  \
	.start()
    
#Printing Time and Country KPI to HDFS as Json file

query_3 = Final_country_time.writeStream \
    .outputMode("Append") \
    .format("json") \
    .option("format","append") \
    .option("truncate", "false") \
    .option("path","time_country_KPI") \
    .option("checkpointLocation", "time_country_KPI_json") \
    .trigger(processingTime="1 minute") \
    .start()

# query termination command
query_1.awaitTermination()
query_2.awaitTermination()
query_3.awaitTermination()