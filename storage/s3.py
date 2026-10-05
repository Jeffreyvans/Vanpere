import boto3
from botocore.config import Config
from django.conf import settings


class S3PhotoStorage:
    """S3-compatible backend (R2, B2, AWS S3, Wasabi)."""

    def __init__(self):
        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4",
                          s3={"addressing_style": settings.S3_ADDRESSING_STYLE}),
        )

    def put(self, key, data, content_type):
        body = data if isinstance(data, bytes) else data.read()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def get_stream(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix):
        pager = self.client.get_paginator("list_objects_v2")
        for page in pager.paginate(Bucket=self.bucket, Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": objs})

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError:
            return False

    def url(self, key, expires=3600, download_name=None):
        params = {"Bucket": self.bucket, "Key": key}
        if download_name:
            params["ResponseContentDisposition"] = f"attachment; filename=\"{download_name}\""
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)

    def presign_upload(self, key, content_type, max_bytes, expires=600):
        """Presigned PUT (R2 does not support POST policies). S3 cannot cap the size of a PUT URL,
        so the size limit is enforced when the upload is finalised (see image_pipeline)."""
        url = self.client.generate_presigned_url(
            "put_object", Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires)
        return {"method": "PUT", "url": url, "headers": {"Content-Type": content_type}}
