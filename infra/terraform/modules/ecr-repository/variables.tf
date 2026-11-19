variable "name" {
  description = "Repository name"
  type        = string
}

variable "image_tag_mutability" {
  description = "IMMUTABLE: a tag that a function uses cannot be overwritten (Lambda resolves it to a digest at deploy time)"
  type        = string
  default     = "IMMUTABLE"

  validation {
    condition     = contains(["IMMUTABLE", "MUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be IMMUTABLE or MUTABLE."
  }
}

variable "keep_images" {
  description = "How many images to keep (older ones expire)"
  type        = number
  default     = 20
}

variable "force_delete" {
  description = "Delete the repository even if it still holds images"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags"
  type        = map(string)
  default     = {}
}
