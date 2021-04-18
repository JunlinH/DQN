# DQN-TensorFlow2


TensorFlow implementation of DQN.

This project is implemented with TensorFlow 2. Specifically, this project includes:
1. The implementation of Deep Q-Networks(DQN)
2. The implementation of Deep Q-learning algorithm


### Requirements
- gym
- tensorflow 2.0 or above
- numpy
- OpenCV-Python
- scipy
- matplotlib


### Usage
First of all, install the prerequisites by running:
```
$pip install requirements.txt
```
To train the model, running the file `DQN.py`. You can use the command line:
```
$ python DQN.py
```
By default this model is trained on the Atari game Pong. To train with a different Atari game, change the name of game in the main function in `DQN.py`.
```
main('Your Game Name Here')
```
If for some reason (loss of Internet connection, etc.), you can run the file `DQN_Reload.py`. This will automatically continues your training from the last automatically saved checkpoint.
```
$ python DQN_Reload.py
```
To evaluate the performance of the model. Run the file `Model_Evaluate.py`. This will give you the average reward per episode metric value of your model.
```
$ python Model_Evaluate.py
```
To plot the results. Run the file `Plot.py`
```
$ python Plot.py
```

### Results:

https://user-images.githubusercontent.com/29801160/115146812-25e68d80-a026-11eb-8a28-7c8ff3dfc99a.mp4

![average_reward_list_cloud (1)](https://user-images.githubusercontent.com/29801160/115146839-4e6e8780-a026-11eb-93e1-e1a0517660b3.png)

### References:
- [Playing Atari with Deep Reinforcement Learning](https://scholar.google.com/scholar_url?url=https://arxiv.org/pdf/1312.5602.pdf%3Fsource%3Dpost_page---------------------------&hl=en&sa=T&oi=gsb-gga&ct=res&cd=0&d=10603651548644623407&ei=pTF8YMT7MovuygSj3pmQBA&scisig=AAGBfm03HCkrreWueYYi3fiB6zZSeGi9Lg)
- [Human-level control through deep reinforcement learning](https://www.nature.com/articles/nature14236?wm=book_wap_0005)
- [DQN](https://github.com/R-Stefano/DQN)
- [DQN-tensorflow](https://github.com/devsisters/DQN-tensorflow#readme)
- [Python TensorFlow Tutorial – Build a Neural Network](https://github.com/JunlinH/DQN-TensorFlow2.4/edit/main/README.md)
- [Speeding up DQN on PyTorch: how to solve Pong in 30 minutes](https://shmuma.medium.com/speeding-up-dqn-on-pytorch-solving-pong-in-30-minutes-81a1bd2dff55)
