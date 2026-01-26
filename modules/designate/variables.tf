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

variable "rabbitmq" {
  description = "Name of the RabbitMQ application"
  type        = string
  nullable    = false
}

variable "memcached" {
  description = "Name of the Memcached application"
  type        = string
  nullable    = false
}

variable "upstream_dns_servers" {
  description = "Designate BIND upstream DNS servers to forward requests to"
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for hostname in var.upstream_dns_servers : can(cidrhost(hostname, 0))])
    error_message = "Upstream DNS server IP addresses must be valid."
  }
}
