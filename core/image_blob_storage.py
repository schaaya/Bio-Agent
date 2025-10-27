import os
import json
import uuid
from azure.storage.blob import BlobServiceClient, ContentSettings
from termcolor import colored

class BlobStorage:
    def __init__(self, connection_string, container_name):
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.container_name = container_name
        
        # Ensure container exists
        try:
            self.container_client = self.blob_service_client.get_container_client(container_name)
            if not self.container_client.exists():
                self.container_client = self.blob_service_client.create_container(container_name)
        except Exception as e:
            print(colored(f"Error creating container: {str(e)}", "red"))
            raise
    
    async def store_fig_json(self, fig_json_list, user_id, timestamp):
        """
        Store the fig_json data in blob storage
        Returns a list of reference IDs that can be used to retrieve the data later
        """
        if not fig_json_list:
            return []
            
        reference_ids = []
        
        for idx, fig_json in enumerate(fig_json_list):
            try:
                # Generate a unique ID for this fig_json
                ref_id = str(uuid.uuid4())
                
                # Create blob name with path structure
                blob_name = f"{user_id}/{timestamp}/fig_json_{ref_id}.json"
                
                # Convert to JSON string if it's not already
                if isinstance(fig_json, dict) or isinstance(fig_json, list):
                    json_str = json.dumps(fig_json)
                else:
                    json_str = fig_json
                
                # Upload to blob storage
                blob_client = self.container_client.get_blob_client(blob_name)
                content_settings = ContentSettings(content_type='application/json')
                blob_client.upload_blob(json_str, overwrite=True, content_settings=content_settings)
                
                # Save reference ID and URL
                reference_ids.append({
                    "ref_id": ref_id,
                    "url": blob_client.url,
                    "index": idx
                })
                
            except Exception as e:
                print(colored(f"Error uploading fig_json to blob storage: {str(e)}", "red"))
                # Continue with other figures even if one fails
        
        return reference_ids
    
    async def retrieve_fig_json(self, user_id, timestamp):
        """
        Retrieve all fig_json data for a specific user and timestamp
        Returns a list of fig_json objects
        """
        try:
            # List all blobs in the user's timestamp folder with fig_json prefix
            prefix = f"{user_id}/{timestamp}/fig_json_"
            blobs = list(self.container_client.list_blobs(name_starts_with=prefix))
            
            result = []
            
            for blob in blobs:
                blob_client = self.container_client.get_blob_client(blob.name)
                json_data = await blob_client.download_blob()
                content = await json_data.content_as_text()
                
                # Try to parse the JSON, but keep as string if it fails
                try:
                    parsed_json = json.loads(content)
                    result.append({
                        "data": parsed_json,
                        "url": blob_client.url,
                        "ref_id": blob.name.split('_')[-1].split('.')[0]
                    })
                except json.JSONDecodeError:
                    result.append({
                        "data": content,
                        "url": blob_client.url,
                        "ref_id": blob.name.split('_')[-1].split('.')[0]
                    })
            
            # Sort by the original order if possible
            return sorted(result, key=lambda x: x.get("ref_id", ""))
            
        except Exception as e:
            print(colored(f"Error retrieving fig_json from blob storage: {str(e)}", "red"))
            return []
    
    async def get_fig_json_by_id(self, ref_id, user_id, timestamp):
        """
        Retrieve a specific fig_json by its reference ID
        """
        try:
            blob_name = f"{user_id}/{timestamp}/fig_json_{ref_id}.json"
            blob_client = self.container_client.get_blob_client(blob_name)
            
            # Check if blob exists
            if not await blob_client.exists():
                return None
                
            json_data = await blob_client.download_blob()
            content = await json_data.content_as_text()
            
            # Try to parse the JSON, but keep as string if it fails
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content
                
        except Exception as e:
            print(colored(f"Error retrieving specific fig_json from blob storage: {str(e)}", "red"))
            return None