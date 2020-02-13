# Final project for Human-computer interaction course
## Cross modal retrieval - Can we retrieve a text which describes an image?

### Datasets
* MS-coco: download and place under "dataset" folder.
* Salicon: download and place under "dataset" folder.
* run `python utils.py`
Or download from ...
### Training
Depends on which sampling algorithm,
 * batch sampling: `python train_two_encoders.py`
 * queue sampling: `python train_queue.py`
 * rerank sampling: `python train_rerank.py`
 
Note: training expects high GPU memory usage, so either use a single GPU with more than 10GB or two GPUs. If it is the former case, change argument `multi` to `0`.
### Inference
See `inference_with_two_enc.py`.
