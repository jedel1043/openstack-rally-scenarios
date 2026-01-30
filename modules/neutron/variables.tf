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

variable "certificates" {
  description = "Name and endpoint of the SSL certificates application"
  type = object({
    name     = string
    endpoint = string
  })
  nullable = false
}

variable "neutron_api_options" {
  description = "Additional options to provide to the Neutron API application"
  type        = map(string)
  nullable    = false
  default     = {}
}

variable "dns_domain" {
  description = "DNS domain name that should be used for building instance hostnames"
  type        = string
  nullable    = false
  validation {
    condition     = var.dns_domain != ""
    error_message = "DNS domain name must not be empty."
  }
}

variable "dns_servers" {
  description = "Designate BIND upstream DNS servers to forward requests to"
  type        = list(string)
  nullable    = false
  validation {
    condition     = length(var.dns_servers) > 0
    error_message = "Must specify at least one DNS server."
  }
}
