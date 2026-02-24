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

variable "certificates" {
  description = "Name and endpoint of the SSL certificates application"
  type = object({
    name     = string
    endpoint = string
  })
  nullable = true
  default  = null
}

variable "vip" {
  description = "Virtual IP to use to front the Keystone service."
  type        = string
  nullable    = false
  validation {
    condition     = var.vip != ""
    error_message = "Virtual IP must not be empty."
  }
}

variable "unit_placement" {
  description = "Information about where to place the service's units in the cloud."
  type        = list(string)
  nullable    = false
  default     = []
}
