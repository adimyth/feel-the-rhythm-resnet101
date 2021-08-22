import pytorch_lightning as pl
import torch
import torch.nn.functional as F
import torchvision.models as models  # type:ignore
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.callbacks.early_stopping import EarlyStopping
from pytorch_lightning.loggers import WandbLogger

# from pytorch_lightning.metrics.functional import accuracy
from torch import nn
from torch.utils.data import DataLoader, random_split
from torchvision import transforms
from torchvision.datasets import ImageFolder  # type:ignore
from torchvision.ops import sigmoid_focal_loss  # type:ignore

# from torchmetrics.functional.classification.accuracy import accuracy

from torchmetrics.functional import accuracy, recall

import wandb  # type:ignore


class FTRDataModule(pl.LightningDataModule):
    def __init__(self, batch_size: int = 64, data_dir: str = ""):
        super().__init__()
        self.data_dir = data_dir
        self.batch_size = batch_size

        self.transform = transforms.Compose(
            [
                transforms.Resize(size=256),
                transforms.CenterCrop(size=224),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

    def setup(self, stage=None):
        ftr_dataset = ImageFolder(self.data_dir)

        num_train = int(0.75 * len(ftr_dataset))
        num_valid = int(0.15 * len(ftr_dataset))
        num_test = len(ftr_dataset) - num_train - num_valid

        self.train, self.val, self.test = random_split(ftr_dataset, [num_train, num_valid, num_test])
        self.train.dataset.transform = self.transform
        self.val.dataset.transform = self.transform
        self.test.dataset.transform = self.transform

    def train_dataloader(self):
        return DataLoader(self.train, batch_size=self.batch_size, shuffle=True, num_workers=16)

    def val_dataloader(self):
        return DataLoader(self.val, batch_size=self.batch_size, num_workers=16)

    def test_dataloader(self):
        return DataLoader(self.test, batch_size=self.batch_size, num_workers=16)


class FTRModel(pl.LightningModule):
    def __init__(self, input_shape, num_classes: int = 2, learning_rate: float = 1e-3):
        super().__init__()

        self.save_hyperparameters()
        self.learning_rate = learning_rate
        self.dim = input_shape
        self.num_classes = num_classes

        self.feature_extractor = models.resnet101(pretrained=True)
        self.feature_extractor.eval()  # layers are frozen by using eval()
        for param in self.feature_extractor.parameters():  # freeze params
            param.requires_grad = False

        n_sizes = self._get_conv_output(input_shape)

        self.classifier = nn.Linear(n_sizes, num_classes)

    # returns the size of the output tensor going into the Linear layer from the conv block
    def _get_conv_output(self, shape):
        batch_size = 1
        tmp_input = torch.autograd.Variable(torch.rand(batch_size, *shape))

        output_feat = self._forward_features(tmp_input)
        n_size = output_feat.data.view(batch_size, -1).size(1)
        return n_size

    # returns the feature tensor from the conv block
    def _forward_features(self, x):
        x = self.feature_extractor(x)
        return x

    def forward(self, x):
        x = self._forward_features(x)
        x = x.view(x.size(0), -1)
        x = F.log_softmax(self.classifier(x), dim=1)

        return x

    def training_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.nll_loss(logits, y)

        # logits = F.softmax_loss(logits)
        # loss = sigmoid_focal_loss(logits, y)

        preds = torch.argmax(logits, dim=1)
        acc = accuracy(preds, y)
        recall_score_0 = recall(preds, y, ignore_index=1)
        recall_score_1 = recall(preds, y, ignore_index=0)
        self.log("train_loss", loss, on_step=True, on_epoch=True, logger=True)
        self.log("train_acc", acc, on_step=True, on_epoch=True, logger=True)
        self.log("train_recall_0", recall_score_0, on_step=True, on_epoch=True, logger=True)
        self.log("train_recall_1", recall_score_1, on_step=True, on_epoch=True, logger=True)

        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.nll_loss(logits, y)

        # logits = F.softmax_loss(logits)
        # loss = sigmoid_focal_loss(logits, y)

        preds = torch.argmax(logits, dim=1)
        acc = accuracy(preds, y)
        recall_score_0 = recall(preds, y, ignore_index=1)
        recall_score_1 = recall(preds, y, ignore_index=0)
        self.log("val_loss", loss, prog_bar=True)
        self.log("val_acc", acc, prog_bar=True)
        self.log("val_recall_0", recall_score_0, prog_bar=True)
        self.log("val_recall_1", recall_score_1, prog_bar=True)
        return loss

    def test_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = F.nll_loss(logits, y)

        # logits = F.softmax_loss(logits)
        # loss = sigmoid_focal_loss(logits, y)

        preds = torch.argmax(logits, dim=1)
        acc = accuracy(preds, y)
        recall_score_0 = recall(preds, y, ignore_index=1)
        recall_score_1 = recall(preds, y, ignore_index=0)
        self.log("test_loss", loss, prog_bar=True)
        self.log("test_acc", acc, prog_bar=True)
        self.log("test_recall_0", recall_score_0, prog_bar=True)
        self.log("test_recall_1", recall_score_1, prog_bar=True)
        return loss

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer


if __name__ == "__main__":
    datamodule = FTRDataModule(batch_size=1024, data_dir="data/v1")
    datamodule.setup()

    # wandb.login()
    # wandb.init(project="feel-the-cnn-rhythm", entity="sharad30")
    # wandb_logger = WandbLogger(project="ftr-lightning", job_type="train")

    early_stop_callback = EarlyStopping(monitor="val_loss", patience=3, verbose=False, mode="min")

    checkpoint_callback = ModelCheckpoint(
        monitor="val_loss",
        dirpath="experiments",
        filename="model/model-{epoch:02d}-{val_loss:.2f}",
        save_top_k=3,
        mode="min",
    )

    model = FTRModel((3, 64, 64), 2)
    trainer = pl.Trainer(
        max_epochs=20,
        progress_bar_refresh_rate=20,
        gpus=1,
        # logger=wandb_logger,
        callbacks=[early_stop_callback, checkpoint_callback],
    )

    trainer.fit(model, datamodule)
    trainer.test()

    # wandb.finish()
