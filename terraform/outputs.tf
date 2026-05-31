# ─────────────────────────────────────────────────────────────────────────────
# Outputs — Multi-Agent Orchestrator Terraform
#
# After `terraform apply`, these values are used to configure:
#   - kubectl (EKS cluster endpoint + kubeconfig command)
#   - Kubernetes secrets (DATABASE_URL, REDIS_URL, ECR URLs)
#   - CI/CD secrets (DOCKER_REGISTRY_URL, EKS_CLUSTER_NAME)
# ─────────────────────────────────────────────────────────────────────────────

# ── VPC ──────────────────────────────────────────────────────────────────────

output "vpc_id" {
  description = "ID of the main VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "IDs of private subnets (EKS nodes, RDS, Redis)"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "IDs of public subnets (Load Balancers)"
  value       = aws_subnet.public[*].id
}

# ── EKS ──────────────────────────────────────────────────────────────────────

output "eks_cluster_name" {
  description = "EKS cluster name — set as EKS_CLUSTER_NAME in GitHub Secrets"
  value       = aws_eks_cluster.main.name
}

output "eks_cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = aws_eks_cluster.main.endpoint
}

output "eks_cluster_certificate" {
  description = "EKS cluster CA certificate (base64 encoded)"
  value       = aws_eks_cluster.main.certificate_authority[0].data
  sensitive   = true
}

output "eks_kubeconfig_command" {
  description = "Command to configure kubectl for this cluster"
  value       = "aws eks update-kubeconfig --name ${aws_eks_cluster.main.name} --region ${var.aws_region}"
}

output "eks_node_role_arn" {
  description = "IAM role ARN for EKS node group"
  value       = aws_iam_role.eks_nodes.arn
}

# ── RDS ──────────────────────────────────────────────────────────────────────

output "rds_endpoint" {
  description = "RDS instance endpoint (host:port)"
  value       = "${aws_db_instance.main.address}:${aws_db_instance.main.port}"
}

output "rds_database_url" {
  description = "DATABASE_URL for the orchestrator-secrets Kubernetes secret"
  value       = "postgresql+asyncpg://${var.rds_username}:${var.rds_password}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/orchestrator"
  sensitive   = true
}

output "rds_instance_id" {
  description = "RDS instance identifier (for backups and DR)"
  value       = aws_db_instance.main.identifier
}

# ── Redis ─────────────────────────────────────────────────────────────────────

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
}

output "redis_url" {
  description = "REDIS_URL for the orchestrator-secrets Kubernetes secret"
  value       = "rediss://:${var.redis_auth_token}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
  sensitive   = true
}

# ── ECR ──────────────────────────────────────────────────────────────────────

output "ecr_backend_url" {
  description = "Backend ECR repository URL — set as DOCKER_REGISTRY_URL in GitHub Secrets (use without /orchestrator-backend)"
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_url" {
  description = "Frontend ECR repository URL"
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecr_registry_url" {
  description = "ECR registry URL (without repository name) — use for DOCKER_REGISTRY_URL"
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

# ── S3 ───────────────────────────────────────────────────────────────────────

output "backup_bucket_name" {
  description = "S3 bucket name for database backups — set as BACKUP_S3_BUCKET"
  value       = aws_s3_bucket.backups.bucket
}

output "backup_bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.backups.arn
}

# ── Monitoring ────────────────────────────────────────────────────────────────

output "sns_alerts_arn" {
  description = "SNS topic ARN for CloudWatch alarm notifications"
  value       = aws_sns_topic.alerts.arn
}

output "cloudwatch_log_group_app" {
  description = "CloudWatch log group for application logs"
  value       = aws_cloudwatch_log_group.app.name
}

# ── Quick-reference: Kubernetes secret creation command ───────────────────────

output "kubectl_create_secret_command" {
  description = "Run this command after 'terraform apply' to create the Kubernetes secret"
  value       = <<-EOT
    # Create the orchestrator namespace first:
    kubectl create namespace orchestrator

    # Then create the secret (fill in real API keys):
    kubectl create secret generic orchestrator-secrets \
      --from-literal=DATABASE_URL="$(terraform output -raw rds_database_url)" \
      --from-literal=REDIS_URL="$(terraform output -raw redis_url)" \
      --from-literal=SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
      --from-literal=ENCRYPTION_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
      --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
      --from-literal=OPENAI_API_KEY="sk-..." \
      -n orchestrator
  EOT
  sensitive = false
}
