terraform {
  required_version = ">= 1.8"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.5"
    }
  }

  # Uncomment after creating the bucket (see README) so state is not kept on one laptop.
  # backend "gcs" {
  #   bucket = "<project_id>-tofu-state"
  #   prefix = "chess-coach"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
