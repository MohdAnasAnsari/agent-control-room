# ─────────────────────────────────────────────────────────────────────────────
# production.tfvars — Production environment values
#
# Usage: terraform apply -var-file=production.tfvars
#
# NEVER commit real secrets (rds_password, redis_auth_token) to git.
# Use: terraform apply -var-file=production.tfvars \
#        -var="rds_password=$RDS_PASSWORD" \
#        -var="redis_auth_token=$REDIS_AUTH_TOKEN"
# ─────────────────────────────────────────────────────────────────────────────

aws_region   = "us-east-1"
environment  = "production"
project_name = "orchestrator"

# Networking
vpc_cidr                = "10.0.0.0/16"
eks_public_access_cidrs = ["0.0.0.0/0"]   # Restrict to your office/VPN CIDR in production

# EKS
kubernetes_version      = "1.29"
eks_node_instance_type  = "t3.medium"
eks_desired_nodes       = 3
eks_min_nodes           = 2
eks_max_nodes           = 10

# RDS — production sizing
rds_instance_class        = "db.t3.medium"
rds_allocated_storage     = 100
rds_max_allocated_storage = 500
rds_multi_az              = true
rds_username              = "orchestrator"
# rds_password            = set via TF_VAR_rds_password or -var flag

# Redis — production with replication
redis_node_type     = "cache.t3.micro"
redis_num_replicas  = 2
# redis_auth_token  = set via TF_VAR_redis_auth_token or -var flag

# Monitoring
alert_email = "anas.ansari@ourworldenergy.com"
