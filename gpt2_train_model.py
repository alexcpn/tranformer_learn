# Module to train the model
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import torch
import shutil
from utils import get_batch
from transformers import  get_linear_schedule_with_warmup # for training
import logging as log
from datetime import datetime
import re
import torch._dynamo.config

print(torch.__version__)
torch.set_float32_matmul_precision('high')
# torch._dynamo.config.log_level = log.DEBUG
# torch._dynamo.config.verbose = True

time_hash=str(datetime.now()).strip()
outfile = "./training/training_" +time_hash +".log"
log.basicConfig(
    level=log.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        log.FileHandler(outfile),
        log.StreamHandler()
    ]
)

model_name = 'gpt2'

tokenizer = GPT2Tokenizer.from_pretrained(model_name)
tokenizer.pad_token = tokenizer.eos_token
#log.info(TokenizerDetails(tokenizer) # model_max_length: 1024 # vocab_size: 50257

# Read the cleaned input text
# original data Canon Camera manual https://gdlp01.c-wss.com/gds/0/0300004730/02/eosrt3-eos1100d-im2-c-en.pdf
input_file_path = './data/clean2.txt' # manually cleaned the indices part
input_file_path = './data/small.txt' # a very small training file to learn
with open(input_file_path, 'r') as f:
    input_text = f.read()
log.info(f"length of dataset in words: {len(input_text):,}") #252,023

encoding = tokenizer(input_text, truncation=False, padding=True,return_tensors='pt')
log.info(f"encoding.input_ids.shape {encoding.input_ids.shape}")
log.info(f"encoding.attention_mask.shape {encoding.attention_mask.shape}")
len_train_data = encoding.input_ids.shape[1]
log.info(f"len_train_data = {len_train_data}")

 # flatten the tensor from  torch.Size([1, 6]) to  torch.Size([48735])
input_ids=encoding.input_ids.view(-1)
attention_mask=encoding.attention_mask.view(-1)
# Note , if we give truncation as False then the token sequence length goes more than model_max_length
# Token indices sequence length is longer than the specified maximum sequence length for this
#  model (23552 > 1024). Running this sequence through the model will result in indexing errors
# However we are not running through the model; We will add it to an array and train with block_size

# Load the T5 model 
model = GPT2LMHeadModel.from_pretrained(model_name)

# # Freeze bottom 10 layers
# #https://towardsdatascience.com/conditional-text-generation-by-fine-tuning-gpt-2-11c1a9fc639d
# for parameter in model.parameters():
#     parameter.requires_grad = False

for i, m in enumerate(model.transformer.h):        
    #Only un-freeze the last n transformer blocks
    if i >= 10:
        for parameter in m.parameters():
            parameter.requires_grad = True 

for parameter in model.transformer.ln_f.parameters():        
    parameter.requires_grad = True

for parameter in model.lm_head.parameters():        
    parameter.requires_grad = True

# Fine-tune the model on the training data
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# # We could optimize training using Pytorch 2.0
# # It neds cuda 11.6+ ,  it crashes as of now
# if int(re.search(r'\d+', torch.__version__).group()) >= 2:
#     # for pytorch 2.0
#     model =torch.compile(model)
#     log.info(f"Compiled the model for speed up")

model.to(device)
# learning_rate = 6e-4 # ??
optimizer = torch.optim.Adam(model.parameters(), lr=3e-5) 

# Set up the training parameters
train_batch_size = 10
block_size = len_train_data-1
if len_train_data > tokenizer.model_max_length:
    block_size = int(tokenizer.model_max_length/8) # tokenizer.model_max_length=1024
num_train_epochs = 10

# Set the optimizer and learning rate scheduler
# num_warmup_steps = 100
# max_grad_norm = 1.0
#optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
num_train_steps = len_train_data // train_batch_size * num_train_epochs
#lr_scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps, num_train_steps)

model.train()
for epoch in range(num_train_epochs):
    log.info(f"Epoch {epoch+1} of {num_train_epochs}")
    epoch_loss = 0
    for i in range(0,len_train_data, block_size):
        # do the batch size manipulation here
        x,y= get_batch(len_train_data,input_ids,attention_mask,device,
            block_size=block_size,batch_size=train_batch_size)
        #x.shape=torch.Size([batch_size, blocksize])
        # attention_mask given by tokenize is array of ones= [1,1,..], that is attend to all tokens
        # if we do not give the parameter, the model will attend to all tokens by default
        outputs = model(input_ids=x,attention_mask=y,labels=x)
        loss = outputs.loss
        loss.backward()
        #torch.nn.utils.clip_grad_norm_(model.parameters(), max_grad_norm)
        optimizer.step()
        #lr_scheduler.step()
        optimizer.zero_grad()
    # Save the model checkpoint every 10th
    checkpoint_dir = f"./test/{model_name}-epoch-{epoch+1}-{time_hash}"
    model.save_pretrained(checkpoint_dir)
    log.info(f"Epoch {epoch} complete. Loss: {loss.item()} saving {checkpoint_dir}")
    # delete the previous save epoch
    checkpoint_dir = f"./model/{model_name}-epoch-{epoch}-{time_hash}"
    try:
        shutil.rmtree(checkpoint_dir)
    except:
        pass


