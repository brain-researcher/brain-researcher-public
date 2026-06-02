from torch import nn


class NiCLIPModel(nn.Module):
    def __init__(self, brain_dim, text_dim, projection_dim=512):
        super().__init__()
        self.brain_projection = nn.Linear(brain_dim, projection_dim)
        self.text_projection = nn.Linear(text_dim, projection_dim)

    def forward(self, brain_features, text_features):
        brain_proj = self.brain_projection(brain_features)
        text_proj = self.text_projection(text_features)
        return brain_proj, text_proj
