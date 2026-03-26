terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_service_account" "m100api" {
  account_id   = "m100api-sa"
  display_name = "m100api runtime SA"
}

resource "google_cloud_run_v2_service" "m100api" {
  name     = "m100api"
  location = var.region

  template {
    service_account = google_service_account.m100api.email
    containers {
      image = var.image_uri

      env {
        name  = "GCS_BUCKET"
        value = "m100boosters"
      }
      env {
        name  = "GCS_QR_PREFIX"
        value = "media/qrcodes"
      }
      env {
        name  = "CORS_ALLOW_ORIGINS"
        value = "https://localtest.beltonbandboosters.com,https://wptest.beltonbandboosters.org,https://shop.beltonmarching100.com,http://localhost:3000,http://127.0.0.1:3000"
      }
    }
  }

  ingress = "INGRESS_TRAFFIC_ALL"
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  location = google_cloud_run_v2_service.m100api.location
  name     = google_cloud_run_v2_service.m100api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_storage_bucket_iam_member" "qr_writer" {
  bucket = "m100boosters"
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.m100api.email}"
}

resource "google_storage_bucket_iam_member" "logo_reader" {
  bucket = "m100boosters"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.m100api.email}"
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run"
  type        = string
  default     = "us-central1"
}

variable "image_uri" {
  description = "Container image URI for Cloud Run service"
  type        = string
}

output "cloud_run_url" {
  description = "Public URL for m100api Cloud Run service"
  value       = google_cloud_run_v2_service.m100api.uri
}