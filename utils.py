import json
import torch
import numpy as np
import torchvision.transforms as transforms
import torchvision.datasets as datasets
import termcolor
import sys
import gc
import time
import threading
import multiprocessing
import pickle
import random
from transformers import DistilBertTokenizer
from PIL import Image

from knockknock import slack_sender


"""
for sending notification when your code finishes
"""
sys.stdin = open("webhook_url.txt", "r")
SLACK_WEBHOOK = sys.stdin.readline().rstrip()


class Logger:
    """
    Print with color, useful when there are too much things printed
    """
    def __init__(self):
        return

    def info(self, information):
        print(termcolor.colored("[INFO] %s" % information, "green", attrs=["bold"]))

    def error(self, information):
        print(termcolor.colored("[ERROR] %s" % information, "red", attrs=["bold"]))


def read_caption(filename="dataset/annotations/captions_val2014.json"):
    with open('cached_data/%s_images_salicon' % "train", 'rb') as fp:
        image_list = pickle.load(fp)
    with open(filename) as json_file:
        data = json.load(json_file)

        id2cap = {}
        for ann in data["annotations"]:
            if ann["image_id"] not in id2cap:
                id2cap[ann["image_id"]] = [ann["caption"]]
            else:
                id2cap[ann["image_id"]].append(ann["caption"])

        filename2id = {}
        for img in data["images"]:
            if img["file_name"] in image_list:
                assert img["file_name"] not in filename2id
                filename2id[img["file_name"]] = img["id"]

    return id2cap, filename2id


def preprocess_path(paths):
    """
    To get only image filename from a path
    :param paths:
    :return:
    """
    return list(map(lambda x: x.split("/")[-1], paths))


def new_get(self, index):
    """
    Also returns the path of the image
    :param self:
    :param index:
    :return:
    """
    path, _ = self.samples[index]
    sample = self.loader(path)
    if self.transform is not None:
        sample = self.transform(sample)
    return sample, path


def new_get_att_maps(self, index):
    """
    Also returns attention map and path
    :param self:
    :param index:
    :return:
    """
    seed = np.random.randint(2147483647)  # make a seed with numpy generator
    norm_transform = transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])

    path, _ = self.samples[index]
    att_path = path.replace("train14/", "").replace("images", "maps").replace(".jpg", ".png")
    _att_map = Image.open(att_path)
    sample = self.loader(path)

    torch.manual_seed(seed)
    random.seed(seed)
    if self.transform is not None:
        sample = self.transform(sample)
        sample = norm_transform(sample)

    torch.manual_seed(seed)
    random.seed(seed)
    if self.transform is not None:
        _att_map = self.transform(_att_map)

    return sample, _att_map, path


def cache_data_helper1(which, limit):
    # Load image list from SALICON
    with open('cached_data/%s_images_salicon' % which, 'rb') as fp:
        image_list = pickle.load(fp)

    ID2CAP, IMAGE2ID = read_caption("dataset/annotations/captions_%s2014.json" % which)
    traindir = "dataset/images/%s" % which
    normalize = transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])
    datasets.ImageFolder.__getitem__ = new_get
    train_loader = torch.utils.data.DataLoader(
        datasets.ImageFolder(traindir, transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            normalize,
        ])),
        batch_size=1, shuffle=False,
        num_workers=2, pin_memory=True)

    images = []
    texts = []
    tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
    longest_length = 0
    print("caching data with %d images" % len(train_loader))

    assert len(train_loader) > 0

    for step, batch in enumerate(train_loader):
        if preprocess_path(batch[1])[0] not in image_list:
            continue
        image, cap = batch[0][0], ID2CAP[IMAGE2ID[preprocess_path(batch[1])[0]]][0]
        sen = tokenizer.encode("[CLS] " + cap + " [SEP]")
        if len(sen) > longest_length:
            longest_length = len(sen)
        images.append(image)
        texts.append(sen)
        if step > limit > 0:
            break
    print("start to save")
    images = torch.stack(images)
    torch.save(images, "cached_data/%s_img" % which)
    with open('cached_data/%s_text' % which, 'wb') as fp:
        pickle.dump(texts, fp)
    print(images.size(), longest_length)


def cache_data_helper2(which):
    with open('cached_data/%s_text' % which, 'rb') as fp:
        texts = pickle.load(fp)

    # longest length to pad
    masks = []
    longest_length = 0
    for du in texts:
        if len(du) > longest_length:
            longest_length = len(du)

    # Pad all sentences to the same length
    print("begin padding with %d" % longest_length)
    for sample in texts:
        mask = [1] * len(sample)
        while len(sample) < longest_length:
            sample.append(0)
            mask.append(0)
        masks.append(mask)
        assert len(sample) == longest_length == len(mask)
    texts, masks = torch.from_numpy(np.array(texts)), torch.from_numpy(np.array(masks))

    print(texts.size(), masks.size())
    torch.save(texts, "cached_data/%s_cap" % which)
    torch.save(masks, "cached_data/%s_mask" % which)


def cache_data(which="val", limit=5):
    """
    Cache data into disk
    :param which: train dataset or val dataset
    :param limit: how many samples to load (-1 for all)
    :return:
    """
    # Load images, transform them, save them and clear memory
    p1 = multiprocessing.Process(target=cache_data_helper1, args=(which, limit))
    p1.start()
    p1.join()
    print("step 1 is done")
    time.sleep(5)

    # Load captions, pad them, save them and clear memory
    p2 = multiprocessing.Process(target=cache_data_helper2, args=(which,))
    p2.start()
    p2.join()
    print("step 2 is done")


def read_relevant_images():
    """
    Indentifying which images in MS-coco have gaze data in SALICON
    :return:
    """
    from os import listdir
    from os.path import isfile, join
    mypath = "dataset/images/train"
    onlyfiles = [f for f in listdir(mypath) if isfile(join(mypath, f))]
    print(onlyfiles)
    with open('cached_data/train_images_salicon', 'wb') as fp:
        pickle.dump(onlyfiles, fp)

    mypath = "dataset/images/val"
    onlyfiles = [f for f in listdir(mypath) if isfile(join(mypath, f))]
    print(onlyfiles)
    with open('cached_data/val_images_salicon', 'wb') as fp:
        pickle.dump(onlyfiles, fp)


def calculate_nb_params(models):
    """
    returns size of model
    :param models:
    :return:
    """
    res = 0
    for model in models:
        model_parameters = filter(lambda p: p.requires_grad, model.parameters())
        params = sum([np.prod(p.size()) for p in model_parameters])
        res += params
    return res


def load_maps(which):
    from os import listdir
    from os.path import isfile, join
    mypath = "dataset/maps/%s" % which
    onlyfiles = [f for f in listdir(mypath) if isfile(join(mypath, f))]

    import re
    m = re.search('COCO_%s2014_(.+?).png' % which, onlyfiles[0])
    index = []
    for item in onlyfiles:
        m = re.search('COCO_%s2014_(.+?).png' % which, item)
        if m:
            index.append(m.group(1))
    index.sort()

    mask = []
    for item in index:
        image_map = 'dataset/maps/' + which + '/COCO_%s2014_' % which + item + '.png'

        img = Image.open(image_map)
        normalize = transforms.Normalize(mean=[0.485],
                                         std=[0.229])
        transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor()
        ])
        mask.append(transform(img).squeeze())

    result = torch.stack(mask)
    return result


def cache_dot(which):
    feature_maps = torch.load("cached_data/%s_img" % which)
    attent_maps = load_maps(which)
    products = []
    for i in range(feature_maps.size()[0]):
        products.append(torch.mul(feature_maps[i], attent_maps[i]))

    result = torch.stack(products)
    torch.save(result, "cached_data/%s_attention" % which)
    return result


if __name__ == "__main__":
    read_relevant_images()
    cache_data("train", -1)
    cache_data("val", -1)


