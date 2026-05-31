# staging.tfvars — Staging environment (cost-optimized)

aws_region   = "us-east-1"
environment  = "staging"
project_name = "orchestrator-staging"

vpc_cidr = "10.1.0.0/16"

kubernetes_version     = "1.29"
eks_node_instance_type = "t3.small"
eks_desired_nodes      = 2
eks_min_nodes          = 1
eks_max_nodes          = 4

rds_instance_class        = "db.t3.micro"
rds_allocated_storage     = 20
rds_max_allocated_storage = 100
rds_multi_az              = false
rds_username              = "orchestrator"

redis_node_type    = "cache.t3.micro"
redis_num_replicas = 1

alert_email = ""
