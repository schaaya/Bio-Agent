# from diagrams import Diagram, Cluster
# from diagrams.aws.analytics import KinesisDataStreams, GlueCrawlers, GlueDataCatalog, Athena
# from diagrams.aws.compute import Lambda
# from diagrams.aws.database import Dynamodb
# from diagrams.aws.storage import S3
# from diagrams.aws.ml import Sagemaker
# from diagrams.aws.management import Cloudwatch

# with Diagram("Data Engineering Architecture (with Crawlers)", show=False):
#     with Cluster("Data Sources"):
#         data_generator = Lambda("Synthetic Data Generator")
    
#     with Cluster("Data Pipeline"):
#         kinesis = KinesisDataStreams("Real-time Stream")
#         lambda_process = Lambda("Data Processing")
#         raw_s3 = S3("Raw Data Lake")
#         processed_s3 = S3("Processed Data")
        
#         # Add Glue components for schema/ETL
#         with Cluster("Schema & Catalog"):
#             crawler = GlueCrawlers("Glue Crawler")
#             catalog = GlueDataCatalog("Data Catalog")
#             crawler >> catalog  # Crawler updates the catalog
        
#         # Add Athena for querying
#         athena = Athena("Analytics Query")
#         catalog >> athena  # Athena uses the catalog
        
#         # Data flow
#         data_generator >> kinesis >> lambda_process
#         lambda_process >> raw_s3
#         raw_s3 >> crawler  # Crawler scans raw data
#         lambda_process >> processed_s3
    
#     with Cluster("Orchestration & ML"):
#         step_function = Lambda("Task Scheduler")
#         sagemaker = Sagemaker("ML Model")
#         dynamo = Dynamodb("Metadata DB")
        
#         processed_s3 >> sagemaker 
#         sagemaker >> dynamo  
    
#     with Cluster("Monitoring"):
#         cloudwatch = Cloudwatch("Metrics/Alerts")
#         step_function >> cloudwatch
    
    
# from diagrams import Diagram, Cluster, Edge
# from diagrams.azure.compute import FunctionApps
# from diagrams.azure.storage import DataLakeStorage
# from diagrams.azure.analytics import StreamAnalyticsJobs, DataExplorerClusters, EventHubs
# from diagrams.azure.database import CosmosDb
# from diagrams.azure.ml import CognitiveServices
# from diagrams.azure.iot import DigitalTwins
# from diagrams.azure.monitor import Monitor
# from diagrams.azure.integration import LogicApps, DataCatalog
# from diagrams.azure.security import KeyVaults
# from diagrams.custom import Custom

from diagrams import Diagram, Cluster
from diagrams.azure.storage import BlobStorage
from diagrams.azure.analytics import StreamAnalyticsJobs, DataExplorerClusters
from diagrams.azure.compute import ContainerInstances
from diagrams.azure.ml import CognitiveServices
from diagrams.azure.integration import LogicApps


with Diagram("Historical + Realtime Analytics to Perception & Actions", show=False):
    # Data sources
    historical = BlobStorage("Historical Data")
    realtime = StreamAnalyticsJobs("Realtime Analytics")
    
    # Data processing that combines both streams
    with Cluster("Data Analysis"):
        combined = DataExplorerClusters("Data Explorer")
    
    # Perception layer (e.g., ML model that perceives insights)
    with Cluster("Perception Layer"):
        perception = CognitiveServices("Perception Model")
    
    # Action layer
    actions = LogicApps("Actions")
    
    # Define the flow
    historical >> combined
    realtime >> perception
    combined >> perception
    perception >> actions
