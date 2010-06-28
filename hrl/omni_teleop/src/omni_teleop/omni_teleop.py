#!/usr/bin/env python  
import roslib
roslib.load_manifest('omni_teleop')

import rospy
import tf
import math
import actionlib
import tf.transformations as tr
import numpy as np
import hrl_lib.tf_utils as tfu
#import threading

from geometry_msgs.msg import PoseStamped
from geometry_msgs.msg import Wrench
from geometry_msgs.msg import Twist
from phantom_omni.msg import PhantomButtonEvent

from actionlib_msgs.msg import *
from pr2_controllers_msgs.msg import *
from pr2_msgs.msg import AccelerometerState

#def tf_as_matrix(tup):
#    return np.matrix(tr.translation_matrix(tup[0])) * np.matrix(tr.quaternion_matrix(tup[1])) 
#
#def matrix_as_tf(mat):
#    return (tr.translation_from_matrix(mat), tr.quaternion_from_matrix(mat))
#
#def transform(to_frame, from_frame, tflistener):
#    return tf_as_matrix(tflistener.lookupTransform(to_frame, from_frame, rospy.Time(0)))
#
#def rotate(to_frame, from_frame, tflistener):
#    t, q = tflistener.lookupTransform(to_frame, from_frame, rospy.Time(0))
#    return np.matrix(tr.quaternion_matrix(q)) 

def limit_range(numb, lower, upper):
    if lower > upper:
        raise RuntimeError('lower bound > upper bound, wa?')
    return max(min(numb, upper), lower)

class GripperOmniHandler:
    def __init__(self, topic, controller):
        rospy.Subscriber(topic, PhantomButtonEvent, self.button_event)
        self.gripper_server = actionlib.SimpleActionClient(controller + '/gripper_action', Pr2GripperCommandAction)
        self.gripper_server.wait_for_server()
        self.gripper_pose = None
        self.gripper_open = False
        self.gripper_close = False
        self.MAX_EFFORT = 40
        self.enabled = True

    def set_enabled(self, v):
        self.enabled = v

    def button_event(self, msg):
        if not (msg.grey_button == 1 and msg.white_button == 1):
            #grey button opens
            if msg.grey_button == 1:
                if self.enabled:
                    self.gripper_server.send_goal(Pr2GripperCommandGoal(
                                         Pr2GripperCommand(position = 0.0, max_effort = self.MAX_EFFORT)),
                                         done_cb = self.gripper_done_cb,
                                         feedback_cb=self.gripper_fb_cb)
                    self.gripper_close = True
            elif msg.grey_button == 0 and self.gripper_pose != None and self.gripper_close:
                self.gripper_server.send_goal(Pr2GripperCommandGoal(
                                     Pr2GripperCommand(position = self.gripper_pose-.01, max_effort = self.MAX_EFFORT))
                                     )
                self.gripper_close = False
                self.gripper_pose = None
                
            #white button closes
            if msg.white_button == 1:
                if self.enabled:
                    self.gripper_server.send_goal(Pr2GripperCommandGoal(
                                         Pr2GripperCommand(position = 0.09, max_effort = self.MAX_EFFORT)),
                                         done_cb = self.gripper_done_cb,
                                         feedback_cb=self.gripper_fb_cb)
                    self.l_gripper_open = True
            elif msg.white_button == 0 and self.gripper_pose != None and self.gripper_open:
                self.gripper_server.send_goal(Pr2GripperCommandGoal(
                                     Pr2GripperCommand(position = self.gripper_pose+.01, max_effort = self.MAX_EFFORT)))
                self.l_gripper_open = False
                self.gripper_pose = None

    def gripper_done_cb(self, state, msg):
        self.gripper_pose = msg.position

    def gripper_fb_cb(self, msg):
        self.gripper_pose = msg.position
        self.effort = msg.effort

class AccelerometerFeedback:
    #self.accel_fb = AccelerometerFeedback(self.OMNI_LEFT + '_sensable', '/accelerometer/l_gripper_motor', 'force_feedback', self.tflistener)
    def __init__(self, dest_frame, accel_topic, force_topic, tflistener):
        rospy.Subscriber(accel_topic, AccelerometerState, self.cb)
        self.viz_pub = rospy.Publisher('omni1_force', PoseStamped)
        self.tflistener = tflistener
        self.dest_frame = dest_frame
        self.force_pub = rospy.Publisher(force_topic, Wrench)
        self.gain = .5

    def cb(self, msg):
        raw_read = [msg.samples[0].x, msg.samples[0].y, msg.samples[0].z]
        g = tr.translation_from_matrix(
                tfu.rotate(msg.header.frame_id, 'base_footprint', self.tflistener) * \
                tr.translation_matrix([0, 0, 9.665])) #empirical gravity
        grav_adjusted = np.array(raw_read) - np.array(g)
        #print grav_adjusted, g

        d_R_m = tfu.rotate(self.dest_frame, 'torso_lift_link', self.tflistener) * \
                tfu.rotate('torso_lift_link', msg.header.frame_id, self.tflistener)

        t_sensable = self.gain * np.array(tr.translation_from_matrix(d_R_m * np.matrix(tr.translation_matrix(grav_adjusted))))
        w = Wrench()
        w.force.x = t_sensable[0]
        w.force.y = t_sensable[1]
        w.force.z = t_sensable[2]
        self.force_pub.publish(w)

        ps = PoseStamped()
        ps.header.frame_id = self.dest_frame
        ps.header.stamp = rospy.get_rostime()
        ps.pose.position.x = t_sensable[0]
        ps.pose.position.y = t_sensable[1]
        ps.pose.position.z = t_sensable[2]
        ps.pose.orientation.w = 1
        self.viz_pub.publish(ps)

class JTWrenchFeedback:
    def __init__(self, 
            wrench_topic, #= '/l_cart/state/wrench', 
            wrench_frame,#= '/l_gripper_tool_frame'): 
            dest_frame, #'omni1_sensable'
            force_feedback_topic, #'omni1_force_feedback
            tflistener): 
        self.wrench_frame = wrench_frame
        self.dest_frame = dest_frame
        self.tflistener = tflistener

        self.omni_fb = rospy.Publisher(force_feedback_topic, Wrench)
        rospy.Subscriber(wrench_topic, Twist, self.wrench_callback)
        self.enable = False

    def set_enable(self, v):
        self.enable = v

    def wrench_callback(self, w):
        wr_tool = [w.linear.x, w.linear.y, w.linear.z]
        df_R_wf = tfu.rotate(self.dest_frame, 'torso_lift_link', self.tflistener) * \
                tfu.rotate('torso_lift_link', self.wrench_frame, self.tflistener)
        wr_df = -.03 * np.array(tr.translation_from_matrix(df_R_wf * tfu.translation_matrix(wr_tool)))
        #print 'called back!', np.linalg.norm(wr_df)

        if self.enable:
            wr = Wrench()
            wr.force.x = wr_df[0]
            wr.force.y = wr_df[1]
            wr.force.z = wr_df[2]
            self.omni_fb.publish(wr)


#class ControlPR2Arm(threading.Thread):
class ControlPR2Arm:

    def __init__(self, omni_name, #='omni1', 
            pr2_control_topic, # = 'l_cart/command_pose',
            gripper_control_topic,  #'l_gripper_controller'
            gripper_tip_frame, #'l_gripper_tool_frame'
            center_in_torso_frame, #=[1,.3,-1], 
            scaling_in_base_frame, #=[3.5, 3., 5.],
            tfbroadcast, #=None,
            tflistener): #=None):

        #threading.Thread.__init__(self)
        self.enabled = False
        self.zero_out_forces = True

        self.X_BOUNDS = [.3, 1.5] #Bound translation of PR2 arms in the X direction (in torso link frame)
        self.kPos = 20.
        self.kPos_close = 70.
        self.omni_name = omni_name
        self.center_in_torso_frame = center_in_torso_frame
        self.scaling_in_base_frame = scaling_in_base_frame
        self.tflistener = tflistener
        self.tfbroadcast = tfbroadcast
        self.gripper_tip_frame = gripper_tip_frame
	#self.start()
        rate = rospy.Rate(30.0)
	for i in range(10):
            self.send_transform_to_link_omni_and_pr2_frame()
            rate.sleep()

        self.omni_fb = rospy.Publisher(self.omni_name + '_force_feedback', Wrench)
        self.pr2_pub = rospy.Publisher(pr2_control_topic, PoseStamped)
        #success = False
        self.scale_omni_l0 = np.abs(self.l0_rotate_base(self.scaling_in_base_frame))
        #while (not success) and (not rospy.is_shutdown()):
	#    try:
        #        success = True
        #        time.sleep(.1)
        #    except tf.LookupException, e:
        #        success = False
        #        print 'tf.LookupException', e
        #    except tf.ConnectivityException, e:
        #        success = False
        #        #print 'tf.ConnectivityException', e

        rospy.Subscriber(self.omni_name + '_pose', PoseStamped, self.omni_pose_cb)
        self.gripper_handler = GripperOmniHandler(self.omni_name + '_button', gripper_control_topic)


#class JTWrenchFeedback:
#    def __init__(self, 
#            wrench_topic, #= '/l_cart/state/wrench', 
#            wrench_frame,#= '/l_gripper_tool_frame'): 
#            dest_frame, #'omni1_sensable'
#            force_feedback_topic, #'omni1_force_feedback
#            tflistener): 

    ##
    # Link this omni to pr2 frame
    def send_transform_to_link_omni_and_pr2_frame(self):
        self.tfbroadcast.sendTransform(self.center_in_torso_frame,
                         tuple(tf.transformations.quaternion_from_euler(0, 0, 0)),
                         rospy.Time.now(),
                         self.omni_name,
                         "/torso_lift_link")
    #def run(self):
    #    rate = rospy.Rate(30.0)
    #    while not rospy.is_shutdown():
    #        self.send_transform_to_link_omni_and_pr2_frame()
    #        rate.sleep()

    ##
    # Rotate a vector from omni_link0 to base_footprint frame
    def l0_rotate_base(self, vec_base):
        m = tfu.translation_matrix(vec_base)
        vec_l0 = tr.translation_from_matrix((tfu.rotate('/base_footprint', '/torso_lift_link', self.tflistener) * \
                                                     tfu.rotate('/torso_lift_link', self.omni_name + '_link0', self.tflistener)).T * m)
        return np.array(vec_l0)

    ##
    # Transform from omni base link to torso lift link taking into account scaling
    def torso_T_omni(self, omni_tip, msg_frame):
        #Transform into link0 so we can scale
        #print 'torso_t_omni', self.omni_name + '_link0', msg_frame
        z_T_6 = tfu.transform(self.omni_name + '_link0', msg_frame, self.tflistener)
        tip_0 = z_T_6 * omni_tip
        tip_0t = (np.array(tr.translation_from_matrix(tip_0)) * np.array(self.scale_omni_l0)).tolist()
        tip_0q = tr.quaternion_from_matrix(tip_0)

        #Transform into torso frame so we can bound arm workspace
        tll_T_0 = tfu.transform('/torso_lift_link', self.omni_name + '_link0', self.tflistener)
        tip_torso_mat = tll_T_0 * tfu.tf_as_matrix([tip_0t, tip_0q])
        tip_tt, tip_tq = tfu.matrix_as_tf(tip_torso_mat)
        tip_tt[0] = limit_range(tip_tt[0], self.X_BOUNDS[0], self.X_BOUNDS[1])
        return tip_tt, tip_tq

    ##
    # Transfrom from torso lift link to link omni base link, taking into account scaling
    def omni_T_torso(self, torso_mat):
        l0_mat = tfu.transform(self.omni_name + '_link0', '/torso_lift_link', self.tflistener) * torso_mat
        l0_t = (np.array(tr.translation_from_matrix(l0_mat)) / np.array(self.scale_omni_l0)).tolist()
        l0_q = tr.quaternion_from_matrix(l0_mat)
        omni_pt_mat = tfu.transform(self.omni_name, self.omni_name + '_link0', self.tflistener) * tfu.tf_as_matrix((l0_t, l0_q))
        return tfu.matrix_as_tf(omni_pt_mat)


    ##
    # Set whether control should be enabled
    def set_control(self, s):
        self.enabled = s
        if self.enabled:
            self.gripper_handler.set_enabled(True)
            self.zero_out_forces = True
        else:
            self.gripper_handler.set_enabled(False)

    ##
    # Callback for pose of omni
    def omni_pose_cb(self, msg):
        if self.enabled:
            #Get the omni's tip pose in the PR2's torso frame
            tip_omni, msg_frame = tfu.posestamped_as_matrix(msg)
            tip_tt, tip_tq = self.torso_T_omni(tip_omni, msg_frame)

            #Publish new arm pose
            ps = PoseStamped()
            ps.header.frame_id = '/torso_lift_link'
            ps.header.stamp = rospy.get_rostime()
            ps.pose.position.x = tip_tt[0]
            ps.pose.position.y = tip_tt[1]
            ps.pose.position.z = tip_tt[2]
            ps.pose.orientation.x = tip_tq[0]
            ps.pose.orientation.y = tip_tq[1]
            ps.pose.orientation.z = tip_tq[2]
            ps.pose.orientation.w = tip_tq[3]
            self.pr2_pub.publish(ps)
            if self.zero_out_forces:
                wr = Wrench()
                wr.force.x = 0 
                wr.force.y = 0 
                wr.force.z = 0 
                self.omni_fb.publish(wr)
                self.zero_out_forces = False
        else:
            tip_omni, msg_frame = tfu.posestamped_as_matrix(msg)
            m_o1 = tfu.transform(self.omni_name, msg_frame, self.tflistener) * tip_omni
            ee_point = np.matrix(tr.translation_from_matrix(m_o1)).T

            #Make the center the current arm tip
            tip_torso = tfu.transform('/torso_lift_link', self.gripper_tip_frame, self.tflistener) \
                                  * tfu.tf_as_matrix(([0.,0.,0.], tr.quaternion_from_euler(0,0,0)))
            center_t, center_q = self.omni_T_torso(tip_torso)
            center_col_vec = np.matrix(center_t).T

            #Transmit some sanity check information
            tip_tt, tip_tq = self.torso_T_omni(tfu.tf_as_matrix((center_t, center_q)), self.omni_name)
            ps = PoseStamped()
            ps.header.frame_id = '/torso_lift_link'
            ps.header.stamp = rospy.get_rostime()
            ps.pose.position.x = tip_tt[0]
            ps.pose.position.y = tip_tt[1]
            ps.pose.position.z = tip_tt[2]
            ps.pose.orientation.x = tip_tq[0]
            ps.pose.orientation.y = tip_tq[1]
            ps.pose.orientation.z = tip_tq[2]
            ps.pose.orientation.w = tip_tq[3]
            self.pr2_pub.publish(ps)

            #Proportional control of force with some hack to keep omni from being unstable
            err_dir = center_col_vec - ee_point
            if np.linalg.norm(err_dir) < .02:
                force_o1 = self.kPos_close * err_dir 
            else:
                if np.linalg.norm(err_dir) < .15:
                    force_o1 = self.kPos * err_dir
                else:
                    force_o1 = 0. * err_dir

            #Send force control info
            force_s = tfu.transform(self.omni_name + '_sensable', self.omni_name, self.tflistener) * np.row_stack((force_o1, np.matrix([1.])))
            wr = Wrench()
            wr.force.x = force_s[0]
            wr.force.y = force_s[1]
            wr.force.z = force_s[2]
            self.omni_fb.publish(wr)


class OmniPR2Teleop:
    def __init__(self):
        rospy.init_node('omni_frames')
        self.enabled = False
        self.tfbroadcast = tf.TransformBroadcaster()
        self.tflistener = tf.TransformListener()

        self.left_controller = ControlPR2Arm(
                                    omni_name ='omni1', 
                                    pr2_control_topic = 'l_cart/command_pose',
                                    gripper_control_topic = 'l_gripper_controller',
                                    gripper_tip_frame = 'l_gripper_tool_frame',
                                    center_in_torso_frame = [1.2, .3, -1], 
                                    scaling_in_base_frame = [3.5, 3., 5.],
                                    tfbroadcast=self.tfbroadcast,
                                    tflistener=self.tflistener)

        self.right_controller = ControlPR2Arm(
                                    omni_name ='omni2', 
                                    pr2_control_topic = 'r_cart/command_pose',
                                    gripper_control_topic = 'r_gripper_controller',
                                    gripper_tip_frame = 'r_gripper_tool_frame',
                                    center_in_torso_frame = [1.2, -.3, -1], 
                                    scaling_in_base_frame = [3.5, 3., 5.],
                                    tfbroadcast=self.tfbroadcast,
                                    tflistener=self.tflistener)
        #self.left_feedback = JTWrenchFeedback(wrench_topic = '/l_cart/state/wrench',
        #                            wrench_frame = '/l_gripper_tool_frame',
        #                            dest_frame = '/omni1_sensable',
        #                            force_feedback_topic = 'omni1_force_feedback',
        #                            tflistener = self.tflistener)

        rospy.Subscriber('omni1_button', PhantomButtonEvent, self.omni_safety_lock_cb)
        rospy.Subscriber('omni2_button', PhantomButtonEvent, self.omni_safety_lock_cb)
        self.set_state(False)

    def omni_safety_lock_cb(self, msg):
        if msg.grey_button == 1 and msg.white_button == 1:
            self.set_state(not self.enabled)

    def set_state(self, s):
        self.enabled = s
        if self.enabled:
            rospy.loginfo('control ENABLED.')
            self.left_controller.set_control(True)
            #self.left_feedback.set_enable(True)
            self.right_controller.set_control(True)
        else:
            rospy.loginfo('control disabled.  Follow potential well to pose of arm.')
            self.left_controller.set_control(False)
            #self.left_feedback.set_enable(False)
            self.right_controller.set_control(False)

    def run(self):
        rate = rospy.Rate(30.0)
        rospy.loginfo('running...')
        while not rospy.is_shutdown():
            self.left_controller.send_transform_to_link_omni_and_pr2_frame()
            self.right_controller.send_transform_to_link_omni_and_pr2_frame()
            rate.sleep()

 
if __name__ == '__main__':
    import time
    o = OmniPR2Teleop()
    o.run()
    #while not rospy.is_shutdown():
    #    time.sleep(1.0)





































#class OmniPR2Teleop:
#
#    def __init__(self):
#        rospy.init_node('omni_frames')
#        self.enabled = False
#        self.zero_out_forces = True
#
#        self.kPos = 20.
#        self.kPos_close = 70.
#        self.OMNI_LEFT = 'omni1'
#        self.LEFT_CENTER_TORSO = [1.0, 0.3, -1.]
#        self.LEFT_SCALE_BASE   = [3.5, 3.,  5.]
#
#        ###############################################################               
#        #Init TF
#        ###############################################################               
#        self.tfbroadcast = tf.TransformBroadcaster()
#        self.tflistener = tf.TransformListener()
#        rate = rospy.Rate(100.0)
#        for i in range(30):
#            self.send_transform_to_link_omni_and_pr2_frame()
#            rate.sleep()
#
#        ###############################################################               
#        #Init PR2 ROS channels
#        ###############################################################               
#        self.X_BOUNDS = [.3, 1.5]
#        self.left_cart_pub = rospy.Publisher('l_cart/command_pose', PoseStamped)
#
#        ###############################################################               
#        #Init Omni ROS channels
#        ###############################################################               
#        #Omni1 for left arm
#        #self.omni_left_last_pose = None
#        self.scale_omni_left_l0 = np.abs(self.l0_rotate_base(self.OMNI_LEFT, self.LEFT_SCALE_BASE))
#        rospy.Subscriber(self.OMNI_LEFT + '_pose', PoseStamped, self.omni_left_pose_cb)
#        rospy.Subscriber(self.OMNI_LEFT + '_button', PhantomButtonEvent, self.omni_left_safety_lock_cb)
#        self.omni_left_fb = rospy.Publisher(self.OMNI_LEFT + '_force_feedback', Wrench)
#        self.omni_left_button_handler = GripperOmniHandler(self.OMNI_LEFT + '_button', 'l_gripper_controller')
#        #self.accel_fb = AccelerometerFeedback(self.OMNI_LEFT + '_sensable', '/accelerometer/l_gripper_motor', 'force_feedback', self.tflistener)
#        print 'OmniPR2Teleop: distances scaled by', self.scale_omni_left_l0
#
#        #Omni2
#        self.OMNI_RIGHT = 'omni2'
#        self.omni_right_button_handler = GripperOmniHandler('omni2_button', 'r_gripper_controller')
#        self.RIGHT_CENTER_TORSO = [1.0, -0.3, -1.]
#        #self.RIGHT_SCALE_BASE = [ 0.635, -0.75, -0.7]
#
#        self.set_state(False)
#
#
#    def send_transform_to_link_omni_and_pr2_frame(self):
#        #self.tfbroadcast.sendTransform((0.6, 0.3, -0.3),
#        self.tfbroadcast.sendTransform(self.LEFT_CENTER_TORSO,
#                         #tuple(tf.transformations.quaternion_from_euler(0, 0, math.pi/2)),
#                         tuple(tf.transformations.quaternion_from_euler(0, 0, 0)),
#                         rospy.Time.now(),
#                         self.OMNI_LEFT,
#                         "torso_lift_link")
#
#        #self.tfbroadcast.sendTransform((0.6, -0.3, -0.3),
#        #                 tuple(tf.transformations.quaternion_from_euler(0, 0, math.pi/2)),
#        #                 rospy.Time.now(),
#        #                 "omni2",
#        #                 "torso_lift_link")
#
#    ##
#    # Rotate a vector from omni_link0 to base_footprint frame
#    def l0_rotate_base(self, omni_name, vec_base):
#        m = np.matrix(tr.translation_matrix(vec_base))
#        vec_omni1_l0 = tr.translation_from_matrix((tfu.rotate('base_footprint', 'torso_lift_link', self.tflistener) * \
#                                                     tfu.rotate('torso_lift_link', omni_name + '_link0', self.tflistener)).T * m)
#        return np.array(vec_omni1_l0)
#
#    def omni_left_safety_lock_cb(self, msg):
#        if msg.grey_button == 1 and msg.white_button == 1:
#            self.set_state(not self.enabled)
#            #self.enabled = not self.enabled
#
#    def set_state(self, s):
#        self.enabled = s
#        if not self.enabled:
#            print 'OmniPR2Teleop: DISABLED'
#            self.omni_left_button_handler.set_enabled(False)
#            self.omni_right_button_handler.set_enabled(False)
#        else:
#            print 'OmniPR2Teleop: ENABLED'
#            self.omni_left_button_handler.set_enabled(True)
#            self.omni_right_button_handler.set_enabled(True)
#            self.zero_out_forces = True
#
#    ##
#    # Transform from omni base link to torso lift link taking into account scaling
#    def torso_T_omni(self, omni_tip, msg_frame):
#        #Transform into link0 so we can scale
#        z_T_6 = tfu.transform(self.OMNI_LEFT + '_link0', msg_frame, self.tflistener)
#        tip_0 = z_T_6 * omni_tip
#        tip_0t = (np.array(tr.translation_from_matrix(tip_0)) * np.array(self.scale_omni_left_l0)).tolist()
#        tip_0q = tr.quaternion_from_matrix(tip_0)
#
#        #Transform into torso frame so we can bound arm workspace
#        tll_T_0 = tfu.transform('/torso_lift_link', self.OMNI_LEFT + '_link0', self.tflistener)
#        tip_torso_mat = tll_T_0 * tfu.tf_as_matrix([tip_0t, tip_0q])
#        tip_tt, tip_tq = tfu.matrix_as_tf(tip_torso_mat)
#        tip_tt[0] = limit_range(tip_tt[0], self.X_BOUNDS[0], self.X_BOUNDS[1])
#        return tip_tt, tip_tq
#
#    ##
#    # Transfrom from torso lift link to link omni base link, taking into account scaling
#    def omni_T_torso(self, torso_mat):
#        l0_mat = tfu.transform(self.OMNI_LEFT + '_link0', 'torso_lift_link', self.tflistener) * torso_mat
#        l0_t = (np.array(tr.translation_from_matrix(l0_mat)) / np.array(self.scale_omni_left_l0)).tolist()
#        l0_q = tr.quaternion_from_matrix(l0_mat)
#        omni_pt_mat = tfu.transform(self.OMNI_LEFT, self.OMNI_LEFT + '_link0', self.tflistener) * tfu.tf_as_matrix((l0_t, l0_q))
#        return tfu.matrix_as_tf(omni_pt_mat)
#
#    ##
#    # Callback for the left omni
#    def omni_left_pose_cb(self, msg):
#        if self.enabled:
#            tip_6, msg_frame = tfu.posestamped_as_matrix(msg)
#            tip_tt, tip_tq = self.torso_T_omni(tip_6, msg_frame)
#
#            #Publish new arm pose
#            ps = PoseStamped()
#            ps.header.frame_id = '/torso_lift_link'
#            ps.header.stamp = rospy.get_rostime()
#            ps.pose.position.x = tip_tt[0]
#            ps.pose.position.y = tip_tt[1]
#            ps.pose.position.z = tip_tt[2]
#            ps.pose.orientation.x = tip_tq[0]
#            ps.pose.orientation.y = tip_tq[1]
#            ps.pose.orientation.z = tip_tq[2]
#            ps.pose.orientation.w = tip_tq[3]
#            self.left_cart_pub.publish(ps)
#            if self.zero_out_forces:
#                wr = Wrench()
#                wr.force.x = 0 
#                wr.force.y = 0 
#                wr.force.z = 0 
#                self.omni_left_fb.publish(wr)
#                self.zero_out_forces = False
#        else:
#
#            tip_6, msg_frame = tfu.posestamped_as_matrix(msg)
#            m_o1 = tfu.transform(self.OMNI_LEFT, msg_frame, self.tflistener) * tip_6
#            ee_point = np.matrix(tr.translation_from_matrix(m_o1)).T
#
#            #Make the center the current arm tip #center = np.matrix([-.10, 0, .30]).T
#            tip_torso = tfu.transform('torso_lift_link', 'l_gripper_tool_frame', self.tflistener) \
#                                  * tfu.tf_as_matrix(([0.,0.,0.], tr.quaternion_from_euler(0,0,0)))
#            center_t, center_q = self.omni_T_torso(tip_torso)
#            center_col_vec = np.matrix(center_t).T
#
#            tip_tt, tip_tq = self.torso_T_omni(tfu.tf_as_matrix((center_t, center_q)), 'omni1')
#            ps = PoseStamped()
#            ps.header.frame_id = '/torso_lift_link'
#            ps.header.stamp = rospy.get_rostime()
#            ps.pose.position.x = tip_tt[0]
#            ps.pose.position.y = tip_tt[1]
#            ps.pose.position.z = tip_tt[2]
#            ps.pose.orientation.x = tip_tq[0]
#            ps.pose.orientation.y = tip_tq[1]
#            ps.pose.orientation.z = tip_tq[2]
#            ps.pose.orientation.w = tip_tq[3]
#            self.left_cart_pub.publish(ps)
#
#            err_dir = center_col_vec - ee_point
#            if np.linalg.norm(err_dir) < .02:
#                force_o1 = self.kPos_close * err_dir 
#            else:
#                if np.linalg.norm(err_dir) < .15:
#                    force_o1 = self.kPos * err_dir
#                else:
#                    force_o1 = 0. * err_dir
#
#            force_s = tfu.transform(self.OMNI_LEFT + '_sensable', self.OMNI_LEFT, self.tflistener) * np.row_stack((force_o1, np.matrix([1.])))
#            wr = Wrench()
#            wr.force.x = force_s[0]
#            wr.force.y = force_s[1]
#            wr.force.z = force_s[2]
#            self.omni_left_fb.publish(wr)
#
#    def run(self):
#        rate = rospy.Rate(10.0)
#        print 'OmniPR2Teleop: running...'
#        while not rospy.is_shutdown():
#            self.send_transform_to_link_omni_and_pr2_frame()
#            rate.sleep()








            #Get the pose for tip (link6) in link0, multiply by scaling factor, publish back into command_pose
            #tip_6 = tfu.translation_matrix([.04, 0, 0]) #* np.matrix(tr.quaternion_matrix(tr.quaternion_from_euler(0, math.pi, 0)))
            #z_T_6 = tfu.transform(self.OMNI_LEFT + '_link0', self.OMNI_LEFT + '_link6', self.tflistener)

            #tip_0 = z_T_6 * tip_6
            #tip_0t = (np.array(tr.translation_from_matrix(tip_0)) * np.array(self.scale_omni_left_l0)).tolist()
            #tip_0q = tr.quaternion_from_matrix(tip_0)

            #tll_T_0 = tfu.transform('/torso_lift_link', self.OMNI_LEFT + '_link0', self.tflistener)
            #tip_torso_mat = tll_T_0 * tfu.tf_as_matrix([tip_0t, tip_0q])
            #tip_tt, tip_tq = tfu.matrix_as_tf(tip_torso_mat)

            #x_bounds = [.3, 1.5]
            #tip_tt[0] = limit_range(tip_tt[0], x_bounds[0], x_bounds[1])

            #ps = PoseStamped()
            #ps.header.frame_id = '/torso_lift_link'
            #ps.header.stamp = rospy.get_rostime()
            #ps.pose.position.x = tip_tt[0]
            #ps.pose.position.y = tip_tt[1]
            #ps.pose.position.z = tip_tt[2]
            #ps.pose.orientation.x = tip_tq[0]
            #ps.pose.orientation.y = tip_tq[1]
            #ps.pose.orientation.z = tip_tq[2]
            #ps.pose.orientation.w = tip_tq[3]
            #self.left_cart_pub.publish(ps)



        #for i in range(30):
        #    self.send_transform_to_link_omni_and_pr2_frame()
        #    rate.sleep()
        #scale_omni1_l0 = np.abs(self.l0_rotate_base('omni1', [1., 3., 2.5]))
        #scale_omni1_l0 = np.abs(self.l0_rotate_base('omni1', self.left_scale_base))


        #self.left_cart_pub = rospy.Publisher('l_cart/command_pose', PoseStamped)
        #PR2 range of motions in base_footprint
        #self.pr2_limits_right = np.matrix([[.23, .94],
        #                                   [-1.15, .64],
        #                                   [.16, 1.67]])
        #self.pr2_limits_left = self.pr2_limits_right.copy()
        #self.pr2_limits_left[1,:] = - self.pr2_limits_left[1,:]
        #Omni range of motion in omni1_link0
        #self.omni_limits = np.matrix([[.06, -.39],
        #                              [-.31, .31],
        #                              [-.08, .44]])
        #torso_T_base = tfu.transform('torso_lift_link', 'base_footprint', self.tflistener)
        #self.right_center_base_foot = ((self.pr2_limits_right[:,0] + self.pr2_limits_right[:,1]) / 2.).A1.tolist()
        #self.left_center_base_foot  = ((self.pr2_limits_left[:,0] + self.pr2_limits_left[:,1]) / 2.).A1.tolist()
        #self.right_center_torso = tr.translation_from_matrix(torso_T_base * tr.translation_matrix(self.right_center_base_foot))
        #self.left_center_torso  = tr.translation_from_matrix(torso_T_base * tr.translation_matrix(self.left_center_base_foot))
        #self.left_center_torso = [ 0.635, 0.255, -0.07171129]

            #f_T_0 = tfu.transform('base_footprint', 'torso_lift_link', self.tflistener) * tfu.transform('/torso_lift_link', '/omni1_link0', self.tflistener)
            #tip_pose = f_T_0 * np.matrix([ps.pose.position.x, ps.pose.position.y, ps.pose.position.z, 1]).T
            #print tip_t, tip_pose.T


            #ps = PoseStamped()
            #ps.header.frame_id = 'base_footprint'
            #ps.header.stamp = rospy.get_rostime()
            #ps.pose.position.x = .4 - self.left_center_base_foot[0]
            #ps.pose.position.y =  self.left_center_base_foot[1]
            #ps.pose.position.z =  self.left_center_base_foot[2]
            #ps.pose.orientation.w = 1
            #self.left_cart_pub.publish(ps)
            #rate.sleep()


        #pr2_range_l0  = (self.l0_rotate_base('omni1', np.abs(self.pr2_limits_left[:,0] - self.pr2_limits_left[:,1]).A1))
        #omni_range_l0 = np.abs(self.omni_limits[:,0] - self.omni_limits[:,1]).A1
        #scale_omni1_l0 = pr2_range_l0 / omni_range_l0

