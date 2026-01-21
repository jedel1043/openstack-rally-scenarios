variable "model_uuid" {
  description = "Model UUID where all applications will be deployed"
  type        = string
  nullable    = false
}

variable "mysql" {
  description = "Name of the MySQL application"
  type        = string
  nullable    = false
}

variable "keystone" {
  description = "Name of the Keystone application"
  type        = string
  nullable    = false
}

variable "rabbit-mq" {
  description = "Name of the RabbitMQ application"
  type        = string
  nullable    = false
}

variable "memcached" {
  description = "Name of the Memcached application"
  type        = string
  nullable    = false
}

variable "upstream_dns_server" {
  description = "Designate BIND upstream DNS server to forward requests to"
  type        = string
  default     = null
}
