
from copy import copy
import numpy as np
import tensorflow as tf

from models.base_model import BaseModel
from tf_common.nn_module import word_dropout
from tf_common.nn_module import encode, attend


class ESIMBaseModel(BaseModel):
    """
    Implementation of ESIM

    Reference
    Paper: Enhanced LSTM for Natural Language Inference
    Keras: https://www.kaggle.com/lamdang/dl-models
    Pytorch: https://github.com/lanwuwei/SPM_toolkit
    """
    def __init__(self, params, logger, init_embedding_matrix=None):
        super(ESIMBaseModel, self).__init__(params, logger, init_embedding_matrix)


    def _soft_attention_alignment(self, x1, x2):
        "Align text representation with neural soft attention"
        # x1: [b, s1, d]
        # x2: [b, s2, d]
        # att: [b, s1, s2]
        att = tf.einsum("abd,acd->abc", x1, x2)
        w_att_1 = tf.nn.softmax(att, dim=1)
        w_att_2 = tf.nn.softmax(att, dim=2)
        x2_att = tf.einsum("abd,abc->acd", x1, w_att_1)
        x1_att = tf.einsum("abd,acb->acd", x2, w_att_2)
        return x1_att, x2_att


    def _interaction_semantic_feature_layer(self, seq_input_left, seq_input_right, seq_len_left, seq_len_right, granularity="word"):
        #### embed
        emb_matrix = self._get_embedding_matrix(granularity)
        emb_seq_left = tf.nn.embedding_lookup(emb_matrix, seq_input_left)
        emb_seq_right = tf.nn.embedding_lookup(emb_matrix, seq_input_right)

        #### dropout
        random_seed = np.random.randint(10000000)
        emb_seq_left = word_dropout(emb_seq_left,
                                    training=self.training,
                                    dropout=self.params["embedding_dropout"],
                                    seed=random_seed)
        random_seed = np.random.randint(10000000)
        emb_seq_right = word_dropout(emb_seq_right,
                                     training=self.training,
                                     dropout=self.params["embedding_dropout"],
                                     seed=random_seed)

        #### encode
        enc_seq_left = encode(emb_seq_left, method=self.params["encode_method"], params=self.params,
                              sequence_length=seq_len_left,
                              mask_zero=self.params["embedding_mask_zero"],
                              scope_name=self.model_name + "enc_seq_%s" % granularity, reuse=False)
        enc_seq_right = encode(emb_seq_right, method=self.params["encode_method"], params=self.params,
                               sequence_length=seq_len_right,
                               mask_zero=self.params["embedding_mask_zero"],
                               scope_name=self.model_name + "enc_seq_%s" % granularity, reuse=True)

        #### align
        ali_seq_left, ali_seq_right = self._soft_attention_alignment(enc_seq_left, enc_seq_right)

        #### compose
        com_seq_left = tf.concat([
            enc_seq_left,
            ali_seq_left,
            enc_seq_left * ali_seq_left,
            enc_seq_left - ali_seq_left,
        ], axis=-1)
        com_seq_right = tf.concat([
            enc_seq_right,
            ali_seq_right,
            enc_seq_right * ali_seq_right,
            enc_seq_right - ali_seq_right,
        ], axis=-1)

        compare_seq_left = encode(com_seq_left, method=self.params["encode_method"], params=self.params,
                                  sequence_length=seq_len_left,
                                  mask_zero=self.params["embedding_mask_zero"],
                                  scope_name=self.model_name + "compare_seq_%s" % granularity, reuse=False)
        compare_seq_right = encode(com_seq_right, method=self.params["encode_method"], params=self.params,
                                   sequence_length=seq_len_right,
                                   mask_zero=self.params["embedding_mask_zero"],
                                   scope_name=self.model_name + "compare_seq_%s" % granularity, reuse=True)

        #### attend
        feature_dim = self.params["encode_dim"]
        att_seq_left = attend(compare_seq_left, context=None, feature_dim=feature_dim,
                              method=self.params["attend_method"],
                              scope_name=self.model_name + "att_seq_%s" % granularity,
                              reuse=False)
        att_seq_right = attend(compare_seq_right, context=None, feature_dim=feature_dim,
                               method=self.params["attend_method"],
                               scope_name=self.model_name + "att_seq_%s" % granularity,
                               reuse=True)
        return tf.concat([att_seq_left, att_seq_right], axis=-1)


    def _get_matching_features(self):
        with tf.name_scope(self.model_name):
            tf.set_random_seed(self.params["random_seed"])

            with tf.name_scope("word_network"):
                sim_word = self._interaction_semantic_feature_layer(
                    self.seq_word_left,
                    self.seq_word_right,
                    self.seq_len_word_left,
                    self.seq_len_word_right,
                    granularity="word")

            with tf.name_scope("char_network"):
                sim_char = self._interaction_semantic_feature_layer(
                    self.seq_char_left,
                    self.seq_char_right,
                    self.seq_len_char_left,
                    self.seq_len_char_right,
                    granularity="char")

            with tf.name_scope("matching_features"):
                matching_features = tf.concat([sim_word, sim_char], axis=-1)

        return matching_features


class ESIM(ESIMBaseModel):
    def __init__(self, params, logger, init_embedding_matrix=None):
        p = copy(params)
        # model config
        p.update({
            "model_name": p["model_name"] + "esim",
            "encode_method": "textbirnn",
            "attend_method": ["ave", "max", "min", "self-attention"],

            # rnn
            "rnn_num_units": 32,
            "rnn_cell_type": "gru",
            "rnn_num_layers": 1,

            # fc block
            "fc_type": "fc",
            "fc_hidden_units": [64 * 4, 64 * 2, 64],
            "fc_dropouts": [0, 0, 0],
        })
        super(ESIMBaseModel, self).__init__(p, logger, init_embedding_matrix)
