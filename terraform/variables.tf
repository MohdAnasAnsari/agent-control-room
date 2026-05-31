# ─────────────────────────────────────────────────────────────────────────────
# Variables — Multi-Agent Orchestrator Terraform
# ─────────────────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (production, staging)"
  type        = string
  validation {
    condition     = contains(["production", "staging"], var.environment)
    error_message = "environment must be 'production' or 'staging'"
  }
}

variable "project_name" {
  description = "Project name used as prefix for all resource names"
  type        = string
  default     = "orchestrator"
}

# ── Networking ────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to access the EKS public API endpoint"
  type        = list(string)
  default     = ["0.0.0.0/0"]   # Restrict to your office/VPN IPs in production
}

# ── EKS ──────────────────────────────────────────────────────────────────────

variable "kubernetes_version" {
  description = "EKS Kubernetes version"
  type        = string
  default     = "1.29"
}

variable "eks_node_instance_type" {
  description = "EC2 instance type for EKS worker nodes"
  type        = string
  default     = "t3.medium"
}

variable "eks_desired_nodes" {
  description = "Desired number of EKS worker nodes"
  type        = number
  default     = 3
}

variable "eks_min_nodes" {
  description = "Minimum number of EKS worker nodes"
  type        = number
  default     = 2
}

variable "eks_max_nodes" {
  description = "Maximum number of EKS worker nodes"
  type        = number
  default     = 10
}

# ── RDS ──────────────────────────────────────────────────────────────────────

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "rds_allocated_storage" {
  description = "Initial RDS storage in GB"
  type        = number
  default     = 50
}

variable "rds_max_allocated_storage" {
  description = "Maximum RDS storage in GB (auto-scaling ceiling)"
  type        = number
  default     = 200
}

variable "rds_multi_az" {
  description = "Enable RDS Multi-AZ for high availability"
  type        = bool
  default     = true
}

variable "rds_username" {
  description = "RDS master username"
  type        = string
  default     = "orchestrator"
  sensitive   = true
}

variable "rds_password" {
  description = "RDS master password (use AWS Secrets Manager in production)"
  type        = string
  sensitive   = true
}

# ── Redis ─────────────────────────────────────────────────────────────────────

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_num_replicas" {
  description = "Number of Redis cache clusters (1 = no replication, 2+ = with replica)"
  type        = number
  default     = 2
}

variable "redis_auth_token" {
  description = "Auth token for Redis TLS (min 16 chars)"
  type        = string
  sensitive   = true
}

# ── Monitoring ────────────────────────────────────────────────────────────────

variable "alert_email" {
  description = "Email address for CloudWatch alarm notifications"
  type        = string
  default     = ""
}
